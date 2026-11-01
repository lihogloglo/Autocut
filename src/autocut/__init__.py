"""autocut: derush a long talking-head recording against its script, export Premiere XML."""

from __future__ import annotations

import argparse
from pathlib import Path

from .align import align
from .media import ensure_ffmpeg, load_audio, probe, rms_envelope
from .premiere_xml import PremiereSequence
from .takes import ADLIB, CHATTER, FAILED, INCOMPLETE, TAKE, resolve_takes, split_pieces
from .text import load_sentences
from .timeline import Options, build_clips
from .transcribe import load_or_transcribe
from .xmeml import write_xml


def _tc(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


def write_report(path: Path, results, words, clips, duration: float) -> None:
    kept = sum(c.src_out - c.src_in for c in clips)
    missing = [r for r in results if not r.takes]
    multi = [r for r in results if len(r.takes) > 1]
    lines = [
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
    ap = argparse.ArgumentParser(prog="autocut", description=__doc__)
    ap.add_argument("source", type=Path,
                    help="long recording (video/audio file) or a Premiere sequence exported as FCP7 XML")
    ap.add_argument("script", type=Path, help="script as .txt, .md or .docx")
    ap.add_argument("--sequence", help="XML input: name of the sequence to use (default: first)")
    ap.add_argument("--audio-track", type=int,
                    help="XML input: audio track to transcribe, 1-based (default: first with a .wav)")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default: next to the video)")
    ap.add_argument("--model", default="large-v3", help="faster-whisper model (large-v3, large-v3-turbo, ...)")
    ap.add_argument("--language", default="fr")
    ap.add_argument("--device", default="auto", help="cuda, cpu or auto (GPU if an NVIDIA card is found)")
    ap.add_argument("--compute-type", default="auto")
    ap.add_argument("--max-pause", type=float, default=0.6, help="cut pauses longer than this inside takes (s)")
    ap.add_argument("--pad-in", type=float, default=0.12)
    ap.add_argument("--pad-out", type=float, default=0.25)
    ap.add_argument("--adlib-words", type=int, default=5,
                    help="off-script speech with at least this many words is kept as ADLIB")
    return ap


def main() -> None:
    run(build_parser().parse_args())


def _pick_device(device: str, compute_type: str) -> tuple[str, str]:
    if device == "auto":
        import ctranslate2
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def run(args: argparse.Namespace) -> Path:
    """Run the whole derush; returns the output folder."""
    src: Path = args.source
    out = args.out or src.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = out / src.stem
    title = src.stem

    ensure_ffmpeg()
    print(f"[1/4] reading {src.name}")
    if src.suffix.lower() == ".xml":
        seq = PremiereSequence(src, args.sequence, args.audio_track)
        print(seq.describe())
        title, duration, decode = seq.name, seq.duration, seq.render_audio
        write = seq.write
    else:
        media = probe(src)
        duration, decode = media.duration, lambda: load_audio(src)
        write = lambda path, name, clips: write_xml(path, media, name, clips)
    audio = None

    def get_audio():
        nonlocal audio
        if audio is None:
            print("  decoding audio")
            audio = decode()
        return audio

    device, compute_type = _pick_device(args.device, args.compute_type)
    print(f"[2/4] transcribing ({args.model} on {device.upper()})")
    if device == "cpu":
        print("  no NVIDIA GPU found: running on the CPU, this can take several times the recording length")
    words = load_or_transcribe(Path(f"{stem}.transcript.json"), src, get_audio,
                               model_name=args.model, language=args.language,
                               device=device, compute_type=compute_type)

    print("[3/4] aligning to script")
    sentences, tokens = load_sentences(args.script)
    tok_sentence = [s.idx for s in sentences for _ in range(s.length)]
    maps = align(words, tokens)
    pieces = split_pieces(words, maps, tok_sentence, args.adlib_words)
    pieces, results = resolve_takes(pieces, sentences, maps, words)

    print("[4/4] writing Premiere XML")
    env = rms_envelope(get_audio())
    opt = Options(max_pause=args.max_pause, pad_in=args.pad_in, pad_out=args.pad_out)
    derush = build_clips(pieces, {TAKE, INCOMPLETE, ADLIB}, words, sentences, env, duration, opt)
    backup = build_clips(pieces, {TAKE, INCOMPLETE, ADLIB, FAILED, CHATTER}, words, sentences, env,
                         duration, opt)
    write(Path(f"{stem}.derush.xml"), f"{title} derush", derush)
    write(Path(f"{stem}.backup.xml"), f"{title} backup (all takes)", backup)
    write_report(Path(f"{stem}.derush.txt"), results, words, derush, duration)

    print(f"\n{stem}.derush.xml   {len(derush)} clips")
    print(f"{stem}.backup.xml   {len(backup)} clips: silences removed, every take kept "
          "(failed takes in Rose, chatter in Brown)")
    print(f"{stem}.derush.txt   per-sentence report")
    print("\n" + "\n".join(Path(f"{stem}.derush.txt").read_text(encoding="utf-8-sig").splitlines()[:2]))
    return out
