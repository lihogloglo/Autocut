"""fauxraccord: sync rushes by sound, derush a talking-head recording against its script, export Premiere XML."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .align import align
from .media import ensure_ffmpeg, probe, rms_envelope
from .premiere_xml import PremiereSequence
from .sync import sync
from .takes import ADLIB, INCOMPLETE, TAKE, resolve_takes, split_pieces
from .text import load_sentences, script_language, set_language
from .timeline import Clip, Options, build_clips, build_triage
from .transcribe import SourceTranscript, Transcriber, Word, transcribe_ranges
from .xmeml import sync_document

SCRIPT_EXT = {".md", ".txt", ".docx"}
MEDIA_EXT = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".wav", ".bwf", ".aif", ".aiff",
             ".flac", ".mp3", ".m4a"}


def _tc(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


def write_report(path: Path, results, words, clips, duration: float, head: list[str] = ()) -> None:
    kept = sum(c.src_out - c.src_in for c in clips)
    missing = [r for r in results if not r.takes]
    multi = [r for r in results if len(r.takes) > 1]
    lines = [
        *head,
        f"Source {_tc(duration)} → derush {_tc(kept)}",
        f"{len(results)} script sentences: {len(results) - len(missing)} found, "
        f"{len(multi)} with alternate takes, {sum(r.impro > 0 for r in results)} improvised, "
        f"{sum(r.incomplete for r in results)} incomplete, "
        f"{len(missing)} never spoken", "",
    ]
    for r in results:
        s = r.sentence
        if not r.takes:
            state = "MISSING"
        else:
            starts = [_tc(words[t[0].words[0]].start) for t in r.takes]
            state = (f"{len(r.takes)} take(s) @ {', '.join(starts)}"
                     + (f", {r.impro} impro" if r.impro else "")
                     + (f", {r.failed} failed" if r.failed else "")
                     + (" INCOMPLETE" if r.incomplete else ""))
        lines.append(f"S{s.idx + 1:03d}  {state:<40}  {s.text[:90]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fauxraccord", description=__doc__)
    ap.add_argument("inputs", nargs="+", type=Path,
                    help="the script (.md, .txt, .docx; optional: without it only the sync is made) and "
                         "either a Premiere sequence exported as FCP7 XML or the rushes: video and audio "
                         "files, or a folder holding them")
    ap.add_argument("--sequence", help="XML input: name of the sequence to use (default: first)")
    ap.add_argument("--audio-track", type=int,
                    help="audio track to transcribe, 1-based (default: first with a .wav)")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default: next to the sources)")
    ap.add_argument("--model", default="large-v3", help="faster-whisper model (large-v3, large-v3-turbo, ...)")
    ap.add_argument("--language", default="auto", help="spoken language: fr, en, or auto (the script's)")
    ap.add_argument("--device", default="auto", help="cuda, cpu or auto (GPU if an NVIDIA card is found)")
    ap.add_argument("--compute-type", default="auto")
    ap.add_argument("--max-pause", type=float, default=0.6, help="cut pauses longer than this inside takes (s)")
    ap.add_argument("--pad-in", type=float, default=0.12)
    ap.add_argument("--pad-out", type=float, default=0.25)
    ap.add_argument("--adlib-words", type=int, default=5,
                    help="off-script speech with at least this many words is kept as ADLIB")
    ap.add_argument("--drift-tolerance", type=float, default=0.005,
                    help="sync: recorder files are re-aligned in segments so clock drift stays under this (s)")
    ap.add_argument("--keep-until", default="0",
                    help="XML input already derushed by hand up to this point: keep it as it is and derush "
                         "the rest. Sequence seconds, or 'auto' to find where the short clips stop")
    return ap


def main() -> None:
    for stream in (sys.stdout, sys.stderr):   # Windows consoles/pipes default to cp1252: "→", "é" would crash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    out = run(build_parser().parse_args())
    write_result(out)


def write_result(path: Path) -> None:
    """The window runs steps as subprocesses: it learns the output file from FAUXRACCORD_RESULT."""
    import os
    if os.environ.get("FAUXRACCORD_RESULT"):
        Path(os.environ["FAUXRACCORD_RESULT"]).write_text(str(path), encoding="utf-8")


def project_title(xml: Path) -> str:
    """'Ep 12.sync.xml' / 'Ep 12.fauxraccord.xml' -> 'Ep 12'."""
    stem = xml.stem
    for suffix in (".sync", ".fauxraccord"):
        if stem.lower().endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _seed_from_sequence_cache(cache: Path, source_key: dict, seq: PremiereSequence, model: str,
                              language: str) -> None:
    """Transcripts used to be cached per sequence: move a matching one into the per-rush cache."""
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if data.get("key") != {**source_key, "model": model, "language": language}:
        return
    words = [Word(**w) for w in data["words"]]
    by_source: dict[Path, SourceTranscript] = {}
    for item, a, b, off in seq._spans():
        src = seq.source(item)
        st = by_source.setdefault(src, SourceTranscript(src, model, language))
        inside = [Word(w.text, round(w.start - a + off, 3), round(w.end - a + off, 3), w.prob)
                  for w in words if a <= (w.start + w.end) / 2 < b]
        st.add(off, off + b - a, inside)
    for st in by_source.values():
        st.save()
    print(f"  reused the transcript of {cache.name}")


def _pick_device(device: str, compute_type: str) -> tuple[str, str]:
    if device == "auto":
        import ctranslate2
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def classify(inputs: list[Path]) -> tuple[Path | None, Path | None, list[Path], str | None]:
    """(script, premiere xml, media files, title from a folder) from the command-line inputs."""
    script, xml, media, title = None, None, [], None
    for p in inputs:
        if p.is_dir():
            found = sorted(f for f in p.iterdir() if f.suffix.lower() in MEDIA_EXT)
            if not found:
                raise ValueError(f"no video or audio file in {p}")
            media += found
            title = title or p.name
        elif not p.is_file():
            raise ValueError(f"not found: {p}")
        elif p.suffix.lower() in SCRIPT_EXT:
            if script:
                raise ValueError(f"two scripts given: {script.name}, {p.name}")
            script = p
        elif p.suffix.lower() == ".xml":
            if xml:
                raise ValueError("give a single Premiere XML")
            xml = p
        else:
            media.append(p)
    if xml and media:
        raise ValueError("give either a Premiere XML or the rushes, not both")
    if not xml and not media:
        raise ValueError("no source: give a Premiere XML, or the video/audio files to sync")
    media = list(dict.fromkeys(m.resolve() for m in media))
    return script, xml, media, title


def _after(clips: list[Clip], keep: float, islands: list[tuple[float, float]] | None = None) -> list[Clip]:
    """The sequence up to `keep` as it is (gaps closed, markers for what was recognised in it), then
    the clips after it."""
    head = []
    for a, b in islands if islands is not None else [(0.0, keep)]:
        head.append(Clip(a, b, "", "", -1, -1, keep=True,
                         markers=[(c.label, c.src_in, c.src_out) for c in clips
                                  if c.label and a <= c.src_in < b and c.src_out <= keep]))
    tail = [c for c in clips if c.src_out > keep]
    for c in tail:
        c.src_in = max(c.src_in, keep)
    return [*head, *tail]


def _stat_key(paths: list[Path]) -> list:
    return [[str(p), p.stat().st_size, p.stat().st_mtime] for p in paths if p.exists()]


def run(args: argparse.Namespace) -> Path:
    """Sync (+ derush when a script is given); returns the .fauxraccord.xml written."""
    script, xml, media, title = classify(args.inputs)
    ensure_ffmpeg()
    sync_lines: list[str] = []
    if xml:
        out = args.out or xml.parent
        title = project_title(xml)
    else:
        infos = [probe(m) for m in media]
        main_file = next((m for m in infos if m.has_video), infos[0]).path
        out = args.out or (media[0].parent if title else main_file.parent)
        title = title or main_file.stem
    out.mkdir(parents=True, exist_ok=True)
    stem = out / title
    xml_out = Path(f"{stem}.fauxraccord.xml" if script else f"{stem}.sync.xml")
    report_out = Path(f"{stem}.fauxraccord.txt" if script else f"{stem}.sync.txt")
    steps = 5 if script else 2

    if xml:
        print(f"[1/{steps}] reading {xml.name}")
        seq = PremiereSequence.from_file(xml, args.sequence, args.audio_track)
        source_key = {"file": str(xml), "size": xml.stat().st_size, "mtime": xml.stat().st_mtime}
    else:
        print(f"[1/{steps}] syncing {len(infos)} file(s) by sound")
        result = sync(infos, Path(f"{stem}.sync.json"), args.drift_tolerance)
        sync_lines = ["Sync", *result.report, ""]
        print("\n".join(result.report))
        if not all(result.synced):
            print("  some files could not be synced: they are at the end of the sync sequence")
        seq = PremiereSequence(sync_document(infos, result, f"{title} 1 sync"), None, args.audio_track)
        analysed = [[str(seq.source(i)), i.start, i.end, i.src_in, i.ticks_in] for i in seq.analysis_track.items]
        source_key = {"sync": hashlib.sha1(json.dumps([_stat_key(seq.sources()), analysed]).encode()).hexdigest()}
    print(seq.describe())
    names = {"sync": seq.name if xml else f"{title} 1 sync", "triage": f"{title} 2 triage",
             "derush": f"{title} 3 derush"}

    if not script:
        print(f"[2/{steps}] writing Premiere XML")
        seq.export(xml_out, title, [(names["sync"], None)])
        report_out.write_text("\n".join(sync_lines) + "\n", encoding="utf-8-sig")
        print(f"\n{xml_out}   1 sequence: {names['sync']}  (no script given: sync only)")
        return xml_out

    keep = 0.0
    if xml and args.keep_until != "0":
        if args.keep_until == "auto":
            keep = seq.derushed_until().get("cutoff") or 0.0
        else:
            keep = float(args.keep_until)
        keep = min(round(keep * float(seq.fps)) / float(seq.fps), seq.duration)
        if keep > 0:
            print(f"  kept as it is (already derushed): 0:00:00 - {_tc(keep)}; "
                  f"derushing the {_tc(seq.duration - keep)} after")

    args.language = script_language(script, args.language)
    set_language(args.language)
    device, compute_type = _pick_device(args.device, args.compute_type)
    print(f"[2/{steps}] transcribing ({args.model} on {device.upper()}, {args.language})")
    if device == "cpu":
        print("  no NVIDIA GPU found: running on the CPU, this can take several times the recording length")
    _seed_from_sequence_cache(Path(f"{stem}.transcript.json"), source_key, seq, args.model, args.language)
    transcriber = Transcriber(model_name=args.model, language=args.language, device=device,
                              compute_type=compute_type)
    # The kept part is transcribed too (once per rush, cached): its sentences get their Sxxx markers.
    transcripts = transcribe_ranges(seq.analysis_needs(), seq.decode, transcriber)
    words = seq.sequence_words(transcripts)

    print(f"[3/{steps}] aligning to script")
    sentences, tokens = load_sentences(script)
    tok_sentence = [s.idx for s in sentences for _ in range(s.length)]
    maps = align(words, tokens)
    pieces = split_pieces(words, maps, tok_sentence, args.adlib_words)
    pieces, results = resolve_takes(pieces, sentences, maps, words)

    print(f"[4/{steps}] cutting")
    print("  decoding audio")
    env = rms_envelope(seq.render_audio(max(0.0, keep - 1.0)))
    opt = Options(max_pause=args.max_pause, pad_in=args.pad_in, pad_out=args.pad_out)
    derush = build_clips(pieces, {TAKE, INCOMPLETE, ADLIB}, words, sentences, env, seq.duration, opt)
    triage = build_triage(pieces, words, sentences, env, seq.duration, opt)
    if keep > 0:
        islands = seq.islands(keep)
        derush, triage = _after(derush, keep, islands), _after(triage, keep, islands)
        sync_lines += [f"Kept as it is (already derushed, {len(islands) - 1} gaps closed): 0:00:00 - {_tc(keep)}", ""]

    print(f"[5/{steps}] writing Premiere XML")
    seq.export(xml_out, title, [(names["sync"], None), (names["triage"], triage), (names["derush"], derush)])
    write_report(report_out, results, words, derush, seq.duration, sync_lines)

    print(f"\n{xml_out}   3 sequences:")
    print(f"  {names['sync']:<32} the rushes, synced")
    print(f"  {names['triage']:<32} everything kept, {len(triage)} clips coloured by take "
          "(failed Rose, chatter Brown, silence Blue)")
    print(f"  {names['derush']:<32} {len(derush)} clips: good takes only, silences removed")
    print(f"{report_out}   per-sentence report")
    print("\n" + "\n".join(report_out.read_text(encoding="utf-8-sig").splitlines()[len(sync_lines):][:2]))
    return xml_out
