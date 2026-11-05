"""Export of the selection: full-resolution files in one folder per section, credits, Premiere XML."""

from __future__ import annotations

import io
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

from ..i18n import tr
from ..media import MediaInfo, ensure_ffmpeg, probe
from ..xmeml import PPRO_TICKS, add_marker, el, file_element, rate, write_document
from .fetch import Fetcher
from .model import Asset, Manifest
from .place import Seq, place_sentences, read_sequence, standalone_copy

PREMIERE_IMAGE = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".psd"}
STILL_SECONDS = 5.0                  # images placed one after the other (no timings)
MIN_STILL_SECONDS, MAX_STILL_SECONDS = 3.0, 12.0   # images placed on their sentence
MAX_CLIP_SECONDS = 60.0
MAX_SPAN_SECONDS = 60.0              # a storyboard card covers its whole beat (spans.json), up to this


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

def _commons_render(fetch: Fetcher, a: Asset, width: int) -> str | None:
    """Wikimedia renders SVG/DjVu/PDF files to PNG/JPEG at the width we ask."""
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


# Premiere refuses stills over 16384 px a side (and slows down well before): only those are reduced.
PREMIERE_MAX_SIDE = 16384


def download_image(fetch: Fetcher, a: Asset, dst_stem: Path) -> Path:
    """The original file, always: only formats Premiere can't read are rendered or converted."""
    url = a.url
    ext = Path(urlparse(url).path).suffix.lower()
    if a.via in ("wikipedia", "commons") and ext in (".svg", ".djvu", ".pdf"):
        # vector / document: let Wikimedia render it as large as it will
        for width in (7680, 3840):
            try:
                url = _commons_render(fetch, a, width) or a.url
                break
            except Exception:
                continue
    r = fetch.get(url, cache=False, timeout=300)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status}")
    ctype = r.headers.get("content-type", "").split(";")[0]
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tif"}.get(ctype)
    Image.MAX_IMAGE_PIXELS = None          # scans of maps and paintings are legitimately huge
    with Image.open(io.BytesIO(r.content)) as im:
        too_big = max(im.size) > PREMIERE_MAX_SIDE
        if ext and not too_big:
            dst = dst_stem.with_suffix(ext)
            dst.write_bytes(r.content)
            return dst
        # webp, avif, gif… -> PNG (lossless); over Premiere's limit -> the largest size it accepts
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        if too_big:
            im.thumbnail((PREMIERE_MAX_SIDE, PREMIERE_MAX_SIDE), Image.LANCZOS)
        dst = dst_stem.with_suffix(".png")
        im.save(dst)
    return dst


# Visually lossless H.264: what Premiere reads natively, without VP9/AV1 decoding trouble.
X264_HQ = ["-c:v", "libx264", "-preset", "slow", "-crf", "12", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"]
PREMIERE_VIDEO = {"h264", "hevc", "prores", "dnxhd", "mpeg2video"}


def _codecs(path: Path) -> tuple[str, str]:
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json",
                          str(path)], capture_output=True, text=True).stdout
    streams = json.loads(out or "{}").get("streams", [])
    v = next((x["codec_name"] for x in streams if x.get("codec_type") == "video"), "")
    au = next((x["codec_name"] for x in streams if x.get("codec_type") == "audio"), "")
    return v, au


def download_video(a: Asset, choice: dict, dst_stem: Path, full_max: float, progress=None) -> Path:
    """Best resolution and frame rate the site has (4K VP9/AV1 included), made Premiere-friendly.
    progress(fraction) is called while the streams download (video then audio: each goes 0 → 1)."""
    import subprocess

    import yt_dlp
    start = choice.get("start", a.start)
    end = choice.get("end", a.end)
    whole = choice.get("full") or start is None

    def hook(d: dict) -> None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if progress and d.get("status") == "downloading" and total:
            progress(d.get("downloaded_bytes", 0) / total)

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True, "progress_hooks": [hook],
            "outtmpl": str(dst_stem) + ".%(ext)s",
            "format": "bv*+ba/b",
            # resolution first, then frame rate; at equal quality prefer H.264/AAC (no re-encode needed)
            "format_sort": ["res", "fps", "vcodec:h264", "acodec:aac", "br"],
            "merge_output_format": "mp4/mkv"}
    if not whole:
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(float(start), float(end))])
        # cutting off-keyframe re-encodes: do it at our quality, not ffmpeg's default CRF 23
        opts["force_keyframes_at_cuts"] = True
        opts["external_downloader_args"] = {"ffmpeg_o": X264_HQ}
    elif a.duration and a.duration > full_max and not choice.get("full"):
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(0, full_max)])
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([a.url])
    found = sorted(dst_stem.parent.glob(dst_stem.name + ".*"), key=lambda p: p.stat().st_size, reverse=True)
    found = [p for p in found if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]
    if not found:
        raise RuntimeError(tr("téléchargement vidéo vide"))
    path = found[0]
    vcodec, acodec = _codecs(path)
    if path.suffix.lower() in (".mp4", ".mov") and vcodec in PREMIERE_VIDEO and acodec in ("aac", "pcm_s16le", ""):
        return path
    dst = dst_stem.parent / (dst_stem.name + ".premiere.mp4")
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(path)]
    if vcodec in PREMIERE_VIDEO:
        args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"]
    else:
        args += X264_HQ
    subprocess.run(args + [str(dst)], check=True, capture_output=True)
    path.unlink()
    final = dst_stem.with_suffix(".mp4")
    dst.replace(final)
    return final


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
        raise ValueError(tr("aucune séquence dans {file}", file=xml_path.name))
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
           full_video_max: float = 600.0, log=print, model: str = "large-v3", auto: bool = False) -> Path:
    """The Premiere XML of the selection at its sentences. What the planche has not downloaded yet is
    downloaded now, into the same médias/ folder (nothing twice). auto: the sentences nothing was chosen
    for get the AI's best candidate (library.auto_picks). Returns the XML."""
    from .library import Library, picks
    manifest = Manifest.load(out / "manifest.json")
    selection = picks(out, auto)
    chosen = [a for a in manifest.assets if a.id in selection]
    if not chosen:
        raise ValueError(tr("rien de sélectionné : cliquez sur des vignettes dans la planche d'abord"))
    ensure_ffmpeg()
    lib = Library(out)
    chosen.sort(key=lambda a: (a.sentence, -a.score))
    log(tr("{n} éléments choisis, fichiers dans {dest}", n=len(chosen), dest=lib.root))

    files: list[tuple[Asset, Path]] = []
    for i, a in enumerate(chosen, 1):
        try:
            choice = selection.get(a.id) or {}
            if not lib.find(a, choice):
                log(tr("  [{i}/{n}] téléchargement : {title}", i=i, n=len(chosen), title=a.title[:60]))
            path = lib.get(a, choice)
            files.append((a, path))
        except Exception as e:
            log(tr("  [{i}/{n}] ÉCHEC {title} : {error}", i=i, n=len(chosen), title=a.title[:50],
                   error=f"{type(e).__name__} {str(e)[:120]}"))
    lib.write_credits()

    xml_path = place(out, files, derush_xml, edit_xml, edit_sequence, log, model, xml_dir=out)
    log(tr("\nFichiers : {dest}\nCrédits : {credits}\nPremiere : {xml}\n"
           "Dans Premiere : Fichier > Importer le .xml (les fichiers viennent avec).",
           dest=lib.root, credits=lib.root / "credits.txt", xml=xml_path))
    return xml_path


def _tc(seconds: float, fps: Fraction) -> str:
    n = round(seconds * float(fps))
    tb = round(float(fps))
    return f"{n // (3600 * tb):02d}:{n // (60 * tb) % 60:02d}:{n // tb % 60:02d}:{n % tb:02d}"


def layout(out: Path, files: list[tuple[int, Path]], derush_xml: Path | None = None, target: Seq | None = None,
           log=print, listen: Path | None = None, model: str = "large-v3") -> tuple[list[tuple[MediaInfo, float, float, float, bool, str]], Seq | None, bool]:
    """Where each exported file goes: (media, start, source in, length, is_still, label) sorted by start,
    in `target` (the edit) or else in the derush; one after the other without either. Also returns the
    sequence used and whether the files are at their sentences."""
    manifest = Manifest.load(out / "manifest.json")
    sentences = {s["idx"]: s for s in manifest.sentences}
    try:        # file name -> last sentence it covers (storyboard beats span several sentences)
        spans = json.loads((out / "spans.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        spans = {}
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
    if not where and ref and listen:         # no Sxxx markers anywhere: find the sentences by ear
        from ..locate import sentence_times as by_ear
        where = by_ear(listen, Path(manifest.script), ref.name, model=model, log=log)
    fps = ref.fps if ref else Fraction(25)
    if ref:
        log(tr("  séquence « {name} » : {n} phrases repérées (via le derush « {derush} »)", name=ref.name,
               n=len(where), derush=derush.name) if derush and target else
            tr("  séquence « {name} » : {n} phrases repérées", name=ref.name, n=len(where)))
        if not where:
            log(tr("  aucune phrase repérée : la voix ne correspond pas au script ?"))

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
            log(tr("  ignoré dans le XML : {file} ({error})", file=path.name, error=e))
            continue
        if where:
            if sentence not in where:
                missing += 1
                continue
            start, end = where[sentence]
            last = spans.get(path.name)
            if still and last is not None and last in where and where[last][1] > start:
                length = min(MAX_SPAN_SECONDS, max(MIN_STILL_SECONDS, where[last][1] - start))
            elif still:    # the image lasts as long as its sentence is spoken
                length = min(MAX_STILL_SECONDS, max(MIN_STILL_SECONDS, end - start))
        else:
            start = cursor
            cursor += length
        label = f"S{sentence + 1:03d} · {sentences[sentence]['text'][:70]}"
        placed.append((m, start, src, length, still, label))
    placed.sort(key=lambda p: p[1])         # takes kept in the edit may be in another order than the script
    if missing:
        log(tr("  {n} élément(s) dont la phrase n'est pas dans « {name} » (coupée au montage ?) : "
               "exportés mais pas placés", n=missing, name=ref.name))
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


def place(out: Path, files: list[tuple[Asset | int, Path]], derush_xml: Path | None = None, edit_xml: Path | None = None,
          edit_sequence: str | None = None, log=print, model: str = "large-v3", kind: str = "B-roll",
          xml_dir: Path | None = None) -> Path:
    """Premiere XML of the exported files at their sentences: a B-roll-only sequence, and a copy of the
    edit (or of `3 derush`) with the B-roll on tracks above. Without timings, one after the other."""
    manifest = Manifest.load(out / "manifest.json")
    target = read_sequence(edit_xml, edit_sequence, prefer="derush") if edit_xml else None
    placed, ref, timed = layout(out, [(getattr(a, "sentence", a), p) for a, p in files], derush_xml, target, log,
                                listen=edit_xml or derush_xml, model=model)
    fps, size = (ref.fps, ref.size) if ref else (Fraction(25), (1920, 1080))
    markers = []
    for p in placed:
        if not markers or markers[-1][1] != p[5]:
            markers.append((p[1], p[5]))

    name = manifest.title[:50]
    xml_path = (xml_dir or out / "export") / f"{slug(manifest.title, 60)} {kind}.xml"
    shared: dict[Path, str] = {}
    seqs = [broll_sequence(f"{name} {kind}", placed, fps, size, markers, files=shared)]
    if ref and timed:
        base = standalone_copy(ref, "edit-broll-sequence", f"{ref.name} + {kind}")
        seqs.append(broll_sequence("", placed, fps, size, [], base=base, files=shared, prefix="edit-broll"))
    write_document(xml_path, seqs, f"{name} {kind}")
    if ref and timed and placed:
        first = min(p[1] for p in placed)
        log(tr("  « {name} » : les illustrations seules, aux timecodes de « {ref} ».\n"
               "     Pour les coller dans votre montage : tout sélectionner, copier, puis dans « {ref} »\n"
               "     tête de lecture à {tc}, piste V2 ciblée, coller.\n"
               "  « {copy} » : votre séquence avec les illustrations sur les pistes au-dessus.",
               name=f"{name} {kind}", ref=ref.name, tc=_tc(first, fps), copy=f"{ref.name} + {kind}"))
    elif placed:
        log(tr("  « {name} » : les illustrations à la suite (pas de derush indiqué : pas de timecodes)",
               name=f"{name} {kind}"))
    return xml_path
