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
from .place import Seq, place_sentences, read_sequence, standalone_copy

PREMIERE_IMAGE = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".psd"}
STILL_SECONDS = 5.0                  # images placed one after the other (no timings)
MIN_STILL_SECONDS, MAX_STILL_SECONDS = 3.0, 12.0   # images placed on their sentence
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
    ext = Path(urlparse(url).path).suffix.lower()
    if a.via in ("wikipedia", "commons") and (ext not in (".jpg", ".jpeg", ".png") or max(a.width, a.height) > 8000):
        # SVG, TIFF, DjVu, PDF, WebP… or huge: let Wikimedia render a 3840 px JPEG/PNG
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
    page = re.sub(r"[?&]utm_[^&#]*", "", a.source_page or a.url)
    bits.append(re.sub(r"^([^?]*)&", lambda m: m.group(1) + "?", page))
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
                   fps: Fraction, size: tuple[int, int], markers: list[tuple[float, str]],
                   base: ET.Element | None = None, files: dict[Path, str] | None = None,
                   prefix: str = "broll") -> ET.Element:
    """placed: (media, start in sequence, source in, length, is_still, label), all in seconds.
    With `base` (a standalone sequence, e.g. the edit), the B-roll goes on new tracks above its own.
    `files` is shared between the sequences of one XML: each file is defined once, at first use."""
    tpf = PPRO_TICKS / float(fps)
    fr = lambda s: round(s * float(fps))   # noqa: E731
    files = {} if files is None else files
    end = max((fr(p[1] + p[3]) for p in placed), default=0)
    if base is not None:
        seq = base
        video, audio = seq.find("media/video"), seq.find("media/audio")
        dur = seq.find("duration")
        if dur is not None:
            dur.text = str(max(int(dur.text or 0), end))
    else:
        seq = ET.Element("sequence", id=f"{prefix}-sequence")
        el(seq, "name", name)
        el(seq, "duration", end)
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
    v_before, a_before = len(video.findall("track")), len(audio.findall("track"))

    lanes: list[float] = []               # end time per video track
    vtracks: list[ET.Element] = []
    atracks: dict[tuple[int, int], ET.Element] = {}
    counts: dict[int, int] = {}
    ids = iter(range(1, 10 ** 9))

    def new_track(parent: ET.Element, **attrs) -> ET.Element:
        """A track right after the existing ones, so the base's tracks keep their numbers."""
        t = ET.Element("track", {k: str(v) for k, v in attrs.items()})
        kids = list(parent)
        last = max((i for i, c in enumerate(kids) if c.tag == "track"), default=None)
        parent.insert(len(kids) if last is None else last + 1, t)
        return t

    def lane_for(start: float, length: float) -> int:
        for i, end in enumerate(lanes):
            if end <= start + 1e-6:
                lanes[i] = start + length
                return i
        lanes.append(start + length)
        vtracks.append(new_track(video))
        return len(lanes) - 1

    def file_ref(m: MediaInfo) -> ET.Element:
        if m.path in files:
            return ET.Element("file", id=files[m.path])
        files[m.path] = f"broll-file-{len(files) + 1}"   # never clashes with the rushes' file ids
        return file_element(m, files[m.path], fps)

    def clipitem(track: ET.Element, m: MediaInfo, start: float, src: float, length: float, channel: int | None):
        attrs = {"id": f"{prefix}-clipitem-{next(ids)}"}
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
        group = [(*clipitem(vtracks[lane], m, start, src, length, None), "video", v_before + lane + 1)]
        if not still:
            for ch in range(min(m.audio_channels, 2)):
                key = (lane, ch)
                if key not in atracks:
                    atracks[key] = new_track(audio, currentExplodedTrackIndex=ch,
                                             totalExplodedTrackCount=min(m.audio_channels, 2),
                                             premiereTrackType="Stereo" if m.audio_channels >= 2 else "Mono")
                ci, n = clipitem(atracks[key], m, start, src, length, ch)
                group.append((ci, n, "audio", a_before + list(atracks).index(key) + 1))
        if len(group) > 1:
            for ci, *_ in group:
                for other, n, mtype, tindex in group:
                    ln = el(ci, "link")
                    el(ln, "linkclipref", other.get("id"))
                    el(ln, "mediatype", mtype)
                    el(ln, "trackindex", tindex)
                    el(ln, "clipindex", n)
    if not video.findall("track"):
        el(video, "track")
    for t, label in markers:
        add_marker(seq, label, fr(t), fr(t) + 1)
    return seq


# --- Main ---------------------------------------------------------------------------------------

def export(out: Path, derush_xml: Path | None = None, edit_xml: Path | None = None, edit_sequence: str | None = None,
           full_video_max: float = 600.0, log=print) -> Path:
    """Download/copy the selection into export/, write the credits and the Premiere XML. Files already
    exported are kept, so running it again only re-places them (e.g. on a newer edit)."""
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

    xml_path = place(out, files, derush_xml, edit_xml, edit_sequence, log)
    log(f"\nFichiers : {dest}\nCrédits : {dest / 'credits.txt'}\nPremiere : {xml_path}\n"
        "Dans Premiere : Fichier > Importer le dossier « export » (un chutier par section) et le .xml.")
    return dest


def _tc(seconds: float, fps: Fraction) -> str:
    n = round(seconds * float(fps))
    tb = round(float(fps))
    return f"{n // (3600 * tb):02d}:{n // (60 * tb) % 60:02d}:{n // tb % 60:02d}:{n % tb:02d}"


def layout(out: Path, files: list[tuple[int, Path]], derush_xml: Path | None = None, target: Seq | None = None,
           log=print) -> tuple[list[tuple[MediaInfo, float, float, float, bool, str]], Seq | None, bool]:
    """Where each exported file goes: (media, start, source in, length, is_still, label) sorted by start,
    in `target` (the edit) or else in the derush; one after the other without either. Also returns the
    sequence used and whether the files are at their sentences."""
    manifest = Manifest.load(out / "manifest.json")
    sentences = {s["idx"]: s for s in manifest.sentences}
    derush = read_sequence(derush_xml, prefer="derush") if derush_xml else None
    ref = target or derush
    where: dict[int, tuple[float, float]] = {}
    if derush and derush.markers:
        where = place_sentences(derush, target)
    elif target and target.markers:          # the edit still carries part 1's Sxxx markers
        where = place_sentences(target)
    elif derush_xml:                         # older part 1 XML: take info in the clip names
        times, *_ = sentence_times(derush_xml)
        where = {i: (t, t + STILL_SECONDS) for i, t in times.items()}
    fps = ref.fps if ref else Fraction(25)
    if ref:
        log(f"  séquence « {ref.name} » : {len(where)} phrases repérées"
            + (f" (via le derush « {derush.name} »)" if derush and target else ""))
        if not where:
            log("  aucune phrase repérée : donnez le .autocut.xml de la partie 1 (marqueurs Sxxx)")

    placed, cursor, missing = [], 0.0, 0
    for sentence, path in files:
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
        if where:
            if sentence not in where:
                missing += 1
                continue
            start, end = where[sentence]
            if still:      # the image lasts as long as its sentence is spoken
                length = min(MAX_STILL_SECONDS, max(MIN_STILL_SECONDS, end - start))
        else:
            start = cursor
            cursor += length
        label = f"S{sentence + 1:03d} · {sentences[sentence]['text'][:70]}"
        placed.append((m, start, src, length, still, label))
    placed.sort(key=lambda p: p[1])         # takes kept in the edit may be in another order than the script
    if missing:
        log(f"  {missing} élément(s) dont la phrase n'est pas dans « {ref.name} » (coupée au montage ?) : "
            "exportés mais pas placés")
    return placed, ref, bool(where)


def lanes(placed: list[tuple[MediaInfo, float, float, float, bool, str]]) -> list[int]:
    """Track per placed item, 0 = lowest: alternatives for one sentence stack up, the rest stays low."""
    ends: list[float] = []
    out = []
    for p in placed:
        k = next((i for i, e in enumerate(ends) if e <= p[1] + 1e-6), len(ends))
        if k == len(ends):
            ends.append(0.0)
        ends[k] = p[1] + p[3]
        out.append(k)
    return out


def place(out: Path, files: list[tuple[Asset, Path]], derush_xml: Path | None = None, edit_xml: Path | None = None,
          edit_sequence: str | None = None, log=print) -> Path:
    """Premiere XML of the exported files at their sentences: a B-roll-only sequence, and a copy of the
    edit (or of `3 derush`) with the B-roll on tracks above. Without timings, one after the other."""
    manifest = Manifest.load(out / "manifest.json")
    target = read_sequence(edit_xml, edit_sequence, prefer="derush") if edit_xml else None
    placed, ref, timed = layout(out, [(a.sentence, p) for a, p in files], derush_xml, target, log)
    fps, size = (ref.fps, ref.size) if ref else (Fraction(25), (1920, 1080))
    markers = []
    for p in placed:
        if not markers or markers[-1][1] != p[5]:
            markers.append((p[1], p[5]))

    name = manifest.title[:50]
    xml_path = out / "export" / f"{slug(manifest.title, 60)} B-roll.xml"
    shared: dict[Path, str] = {}
    seqs = [broll_sequence(f"{name} B-roll", placed, fps, size, markers, files=shared)]
    if ref and timed:
        base = standalone_copy(ref, "edit-broll-sequence", f"{ref.name} + B-roll")
        seqs.append(broll_sequence("", placed, fps, size, [], base=base, files=shared, prefix="edit-broll"))
    write_document(xml_path, seqs, f"{name} B-roll")
    if ref and timed and placed:
        first = min(p[1] for p in placed)
        log(f"  « {name} B-roll » : les illustrations seules, aux timecodes de « {ref.name} ».\n"
            f"     Pour les coller dans votre montage : tout sélectionner, copier, puis dans « {ref.name} »\n"
            f"     tête de lecture à {_tc(first, fps)}, piste V2 ciblée, coller.\n"
            f"  « {ref.name} + B-roll » : votre séquence avec les illustrations sur les pistes au-dessus.")
    elif placed:
        log(f"  « {name} B-roll » : les illustrations à la suite (pas de derush indiqué : pas de timecodes)")
    return xml_path
