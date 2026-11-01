"""Export of the selection: full-resolution files in one folder per section, credits, Premiere XML."""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

from ..media import MediaInfo, ensure_ffmpeg, probe
from ..xmeml import PPRO_TICKS, add_marker, el, file_element, rate, write_document
from .fetch import Fetcher
from .model import Asset, Manifest

PREMIERE_IMAGE = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".psd"}
STILL_SECONDS = 5.0
MAX_CLIP_SECONDS = 60.0


def slug(text: str, n: int = 50) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s-]", " ", text)
    return " ".join(text.split())[:n].strip() or "sans titre"


def load_selection(out: Path) -> dict[str, dict]:
    try:
        return json.loads((out / "selection.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --- Downloads ----------------------------------------------------------------------------------

def _commons_render(fetch: Fetcher, a: Asset, width: int = 3840) -> str | None:
    """Wikimedia renders SVG/TIFF/huge files to PNG/JPEG at the width we ask."""
    p = urlparse(a.source_page)
    if "/wiki/" not in p.path:
        return None
    title = unquote(p.path.split("/wiki/", 1)[1])
    data = fetch.json(f"https://{p.netloc}/w/api.php", {"action": "query", "format": "json", "formatversion": 2,
                                                        "titles": title, "prop": "imageinfo", "iiprop": "url",
                                                        "iiurlwidth": width})
    pages = data.get("query", {}).get("pages", [])
    ii = (pages[0].get("imageinfo") or [{}])[0] if pages else {}
    return ii.get("thumburl")


def download_image(fetch: Fetcher, a: Asset, dst_stem: Path) -> Path:
    url = a.url
    if a.via in ("wikipedia", "commons") and (a.note in ("svg", "tiff") or max(a.width, a.height) > 8000):
        url = _commons_render(fetch, a) or url
    r = fetch.get(url, cache=False, timeout=180)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status}")
    ctype = r.headers.get("content-type", "").split(";")[0]
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tif"}.get(ctype)
    if ext:
        dst = dst_stem.with_suffix(ext)
        dst.write_bytes(r.content)
        return dst
    with Image.open(io.BytesIO(r.content)) as im:       # webp, avif, gif, svg-less formats -> PNG
        dst = dst_stem.with_suffix(".png")
        im.convert("RGBA" if "A" in im.getbands() else "RGB").save(dst)
    return dst


def download_video(a: Asset, choice: dict, dst_stem: Path, full_max: float) -> Path:
    import yt_dlp
    start = choice.get("start", a.start)
    end = choice.get("end", a.end)
    whole = choice.get("full") or start is None
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "outtmpl": str(dst_stem) + ".%(ext)s",
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
            "merge_output_format": "mp4"}
    if not whole:
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(float(start), float(end))])
        opts["force_keyframes_at_cuts"] = True
    elif a.duration and a.duration > full_max and not choice.get("full"):
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(0, full_max)])
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([a.url])
    found = sorted(dst_stem.parent.glob(dst_stem.name + ".*"), key=lambda p: p.stat().st_size, reverse=True)
    found = [p for p in found if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]
    if not found:
        raise RuntimeError("téléchargement vidéo vide")
    return found[0]


# --- Credits ------------------------------------------------------------------------------------

def credit_line(a: Asset) -> str:
    bits = [a.title or "Sans titre"]
    if a.author:
        bits.append(a.author)
    if a.kind == "screenshot":
        bits = [f"Capture d'écran : {a.title}"]
    if a.licence:
        bits.append(a.licence + (f" ({a.licence_url})" if a.licence_url and a.licence_url not in a.licence else ""))
    bits.append(a.source_page or a.url)
    return " — ".join(b for b in bits if b)


# --- Premiere -----------------------------------------------------------------------------------

def sentence_times(xml_path: Path) -> tuple[dict[int, float], Fraction, tuple[int, int], str]:
    """Sentence index -> start (s) in the derush sequence, read from part 1's 'Sxxx' markers."""
    root = ET.parse(xml_path).getroot()
    seqs = list(root.iter("sequence"))
    if not seqs:
        raise ValueError(f"aucune séquence dans {xml_path.name}")
    seq = next((s for s in reversed(seqs) if (s.findtext("name") or "").lower().endswith("derush")), seqs[-1])
    tb = int(seq.findtext("rate/timebase") or 25)
    ntsc = (seq.findtext("rate/ntsc") or "").upper() == "TRUE"
    fps = Fraction(tb * 1000, 1001) if ntsc else Fraction(tb)
    w = int(seq.findtext("media/video/format/samplecharacteristics/width") or 1920)
    h = int(seq.findtext("media/video/format/samplecharacteristics/height") or 1080)
    times: dict[int, float] = {}
    # Current part 1 writes sequence markers; older versions named the clips themselves.
    spans = [(m.findtext("name"), m.findtext("in"), m.findtext("out")) for m in seq.findall("marker")]
    if not spans:
        track = seq.find("media/video/track")
        items = track.findall("clipitem") if track is not None else []
        spans = [(c.findtext("name"), c.findtext("start"), c.findtext("end")) for c in items]
    for name, t_in, t_out in spans:
        mm = re.match(r"S(\d{3})(?:[–-]S(\d{3}))?", name or "")
        if not mm:
            continue
        a = int(mm.group(1)) - 1
        b = int(mm.group(2)) - 1 if mm.group(2) else a
        t0 = int(t_in or 0) / float(fps)
        t1 = int(t_out or 0) / float(fps)
        for k, idx in enumerate(range(a, b + 1)):
            t = t0 + (t1 - t0) * k / (b - a + 1)
            times[idx] = min(times.get(idx, t), t)
    return times, fps, (w, h), seq.findtext("name") or "derush"


def broll_sequence(name: str, placed: list[tuple[MediaInfo, float, float, float, bool, str]],
                   fps: Fraction, size: tuple[int, int], markers: list[tuple[float, str]]) -> ET.Element:
    """placed: (media, start in sequence, source in, length, is_still, label), all in seconds."""
    tpf = PPRO_TICKS / float(fps)
    fr = lambda s: round(s * float(fps))   # noqa: E731
    seq = ET.Element("sequence", id="broll-sequence")
    el(seq, "name", name)
    el(seq, "duration", max((fr(p[1] + p[3]) for p in placed), default=0))
    rate(seq, fps)
    media = el(seq, "media")
    video = el(media, "video")
    vsc = el(el(video, "format"), "samplecharacteristics")
    el(vsc, "width", size[0])
    el(vsc, "height", size[1])
    el(vsc, "pixelaspectratio", "square")
    rate(vsc, fps)
    audio = el(media, "audio")
    el(audio, "numOutputChannels", 2)
    asc = el(el(audio, "format"), "samplecharacteristics")
    el(asc, "depth", 16)
    el(asc, "samplerate", 48000)

    lanes: list[float] = []               # end time per video track
    vtracks: list[ET.Element] = []
    atracks: dict[tuple[int, int], ET.Element] = {}
    files: dict[Path, str] = {}
    counts: dict[int, int] = {}
    ids = iter(range(1, 10 ** 9))

    def lane_for(start: float, length: float) -> int:
        for i, end in enumerate(lanes):
            if end <= start + 1e-6:
                lanes[i] = start + length
                return i
        lanes.append(start + length)
        vtracks.append(el(video, "track"))
        return len(lanes) - 1

    def file_ref(m: MediaInfo) -> ET.Element:
        if m.path in files:
            return ET.Element("file", id=files[m.path])
        files[m.path] = f"file-{len(files) + 1}"
        f = file_element(m, files[m.path], fps)
        return f

    def clipitem(track: ET.Element, m: MediaInfo, start: float, src: float, length: float, channel: int | None):
        attrs = {"id": f"broll-clipitem-{next(ids)}"}
        if channel is not None:
            attrs["premiereChannelType"] = "stereo" if m.audio_channels == 2 else "mono"
        ci = el(track, "clipitem", **attrs)
        el(ci, "name", m.path.name)
        el(ci, "enabled", "TRUE")
        el(ci, "duration", fr(m.duration))
        rate(ci, fps)
        el(ci, "start", fr(start))
        el(ci, "end", fr(start + length))
        el(ci, "in", fr(src))
        el(ci, "out", fr(src) + fr(start + length) - fr(start))
        el(ci, "pproTicksIn", round(src * PPRO_TICKS))
        el(ci, "pproTicksOut", round(src * PPRO_TICKS + (fr(start + length) - fr(start)) * tpf))
        ci.append(file_ref(m))
        if channel is None:
            el(ci, "compositemode", "normal")
        else:
            st = el(ci, "sourcetrack")
            el(st, "mediatype", "audio")
            el(st, "trackindex", channel + 1)
        counts[id(track)] = counts.get(id(track), 0) + 1
        return ci, counts[id(track)]

    for m, start, src, length, still, _ in placed:
        lane = lane_for(start, length)
        group = [(*clipitem(vtracks[lane], m, start, src, length, None), "video", lane + 1)]
        if not still:
            for ch in range(min(m.audio_channels, 2)):
                key = (lane, ch)
                if key not in atracks:
                    atracks[key] = el(audio, "track", currentExplodedTrackIndex=ch,
                                      totalExplodedTrackCount=min(m.audio_channels, 2),
                                      premiereTrackType="Stereo" if m.audio_channels >= 2 else "Mono")
                ci, n = clipitem(atracks[key], m, start, src, length, ch)
                group.append((ci, n, "audio", list(atracks).index(key) + 1))
        if len(group) > 1:
            for ci, *_ in group:
                for other, n, mtype, tindex in group:
                    ln = el(ci, "link")
                    el(ln, "linkclipref", other.get("id"))
                    el(ln, "mediatype", mtype)
                    el(ln, "trackindex", tindex)
                    el(ln, "clipindex", n)
    if not vtracks:
        el(video, "track")
    for t, label in markers:
        add_marker(seq, label, fr(t), fr(t) + 1)
    return seq


# --- Main ---------------------------------------------------------------------------------------

def export(out: Path, derush_xml: Path | None = None, full_video_max: float = 600.0, log=print) -> Path:
    manifest = Manifest.load(out / "manifest.json")
    selection = load_selection(out)
    chosen = [a for a in manifest.assets if a.id in selection]
    if not chosen:
        raise ValueError("rien de sélectionné : cliquez sur des vignettes dans la planche d'abord")
    ensure_ffmpeg()
    fetch = Fetcher(out / "cache")
    dest = out / "export"
    dest.mkdir(exist_ok=True)
    sections = {s["idx"]: s for s in manifest.sections}
    sentences = {s["idx"]: s for s in manifest.sentences}
    chosen.sort(key=lambda a: (a.sentence, -a.score))
    log(f"Export de {len(chosen)} éléments vers {dest}")

    files: list[tuple[Asset, Path]] = []
    per_sentence: dict[int, int] = {}
    for i, a in enumerate(chosen, 1):
        sec = sections[sentences[a.sentence]["section"]]
        folder = dest / f"{sec['idx']:02d} {slug(sec['title'] or 'Début', 40)}"
        folder.mkdir(exist_ok=True)
        n = per_sentence[a.sentence] = per_sentence.get(a.sentence, 0) + 1
        stem = folder / f"S{a.sentence + 1:03d}-{n:02d} {a.via} - {slug(a.title)}"
        existing = [p for p in folder.glob(stem.name + ".*") if not p.name.endswith((".part", ".ytdl"))]
        try:
            if existing:
                path = existing[0]
            elif a.file:
                src = out / a.file
                path = stem.with_suffix(src.suffix)
                shutil.copy2(src, path)
            elif a.kind == "video":
                log(f"  [{i}/{len(chosen)}] vidéo : {a.title[:60]}")
                path = download_video(a, selection.get(a.id) or {}, stem, full_video_max)
            else:
                path = download_image(fetch, a, stem)
            files.append((a, path))
            log(f"  [{i}/{len(chosen)}] {path.relative_to(dest)}")
        except Exception as e:
            log(f"  [{i}/{len(chosen)}] ÉCHEC {a.title[:50]} : {type(e).__name__} {str(e)[:120]}")

    # Credits, grouped by section, ready to paste in a video description.
    lines = [f"Sources — {manifest.title}", ""]
    rows = []
    last = None
    for a, path in files:
        sec = sections[sentences[a.sentence]["section"]]
        if sec["idx"] != last:
            lines += ["", f"== {sec['title'] or 'Début'} =="]
            last = sec["idx"]
        lines.append(f"- {credit_line(a)}")
        rows.append([path.relative_to(dest).as_posix(), a.sentence + 1, a.kind, a.via, a.rights, a.title, a.author,
                     a.licence, a.licence_url, a.source_page, a.url, a.credit, a.note])
    (dest / "credits.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
    with (dest / "credits.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["fichier", "phrase", "type", "source", "droits", "titre", "auteur", "licence", "url licence",
                    "page", "url", "crédit", "note"])
        w.writerows(rows)

    # Premiere: B-roll sequence, at the derush times when a derush XML is given.
    times, fps, size, seq_name = {}, Fraction(25), (1920, 1080), ""
    if derush_xml:
        times, fps, size, seq_name = sentence_times(derush_xml)
        log(f"  séquence derush « {seq_name} » : {len(times)} phrases repérées")
    placed, markers, cursor, missing = [], [], 0.0, 0
    for a, path in files:
        try:
            if path.suffix.lower() in PREMIERE_IMAGE:
                with Image.open(path) as im:
                    w, h = im.size
                m = MediaInfo(path.resolve(), 3600.0, fps, w, h, 0, 48000)
                still, length, src = True, STILL_SECONDS, 0.0
            else:
                m = probe(path)
                still, src = False, 0.0
                length = min(m.duration, MAX_CLIP_SECONDS)
        except Exception as e:
            log(f"  ignoré dans le XML : {path.name} ({e})")
            continue
        if derush_xml:
            if a.sentence not in times:
                missing += 1
                continue
            start = times[a.sentence]
        else:
            start = cursor
            cursor += length
        label = f"S{a.sentence + 1:03d} · {sentences[a.sentence]['text'][:70]}"
        if not markers or markers[-1][1] != label:
            markers.append((start, label))
        placed.append((m, start, src, length, still, label))
    xml_path = dest / f"{slug(manifest.title, 60)} B-roll.xml"
    seq = broll_sequence(f"{manifest.title[:50]} B-roll", placed, fps, size, markers)
    write_document(xml_path, [seq], f"{manifest.title[:50]} B-roll")
    if missing:
        log(f"  {missing} éléments sans phrase repérée dans le derush : pas placés dans la séquence (mais exportés)")
    log(f"\nFichiers : {dest}\nCrédits : {dest / 'credits.txt'}\nPremiere : {xml_path} "
        f"({'aux temps du derush' if derush_xml else 'à la suite, 5 s par image'})\n"
        "Dans Premiere : Fichier > Importer le dossier « export » (un chutier par section) et le .xml.")
    return dest
