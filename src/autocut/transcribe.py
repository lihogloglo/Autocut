"""Word-level transcription with faster-whisper, cached to JSON."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import sysconfig
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .media import SAMPLE_RATE

# Whisper tends to "clean up" false starts. A disfluent prompt nudges it to
# transcribe repeated words and restarts verbatim, which is exactly what the
# retake detection needs.
DISFLUENT_PROMPT = (
    "Euh, alors, le... le traité, euh, le traité de Versailles est... "
    "Non, attends. Bon. Le traité de Versailles est signé en 1919."
)


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float


def _add_cuda_dll_dirs() -> None:
    """On Windows, pip-installed NVIDIA DLLs are not on the loader path."""
    if sys.platform != "win32":
        return
    nvidia = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    for bin_dir in nvidia.glob("*/bin"):
        os.add_dll_directory(str(bin_dir))
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


class Transcriber:
    """faster-whisper, loaded on first use and kept for the following calls."""

    def __init__(self, *, model_name: str, language: str, device: str, compute_type: str):
        self.model_name, self.language, self.device, self.compute_type = model_name, language, device, compute_type
        self._model = None

    def __call__(self, audio: np.ndarray, progress=None) -> list[Word]:
        """Words of `audio`; progress(seconds done) is called as segments come out."""
        if self._model is None:
            _add_cuda_dll_dirs()
            from faster_whisper import WhisperModel
            print(f"  loading {self.model_name} (the first time: ~3 GB download)")
            self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        segments, _ = self._model.transcribe(
            audio,
            language=self.language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
            condition_on_previous_text=False,
            initial_prompt=DISFLUENT_PROMPT,
            beam_size=5,
        )
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                words.append(Word(w.word.strip(), round(w.start, 3), round(w.end, 3), round(w.probability, 3)))
            if progress:
                progress(seg.end)
        return [w for w in words if w.text]


# --- Per-rush cache -----------------------------------------------------------------------------------
# Transcripts are kept per source file, in source time, with the ranges already transcribed. Any
# sequence built from the same rushes (the sync, a re-export, a half-derushed edit) reuses them and
# only the parts never heard before get transcribed.

CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "autocut" / "transcripts"
MERGE_GAP = 30.0   # source ranges closer than this are transcribed as one stretch (context for whisper)
OVERLAP = 1.0      # each new stretch starts/ends this far inside its neighbours, for words on the seam


def _merge(ranges: list[tuple[float, float]], gap: float = 0.0) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _subtract(ranges: list[tuple[float, float]], covered: list[tuple[float, float]],
              min_len: float = 0.5) -> list[tuple[float, float]]:
    out = []
    for a, b in ranges:
        pos = a
        for ca, cb in covered:
            if cb <= pos or ca >= b:
                continue
            if ca - pos >= min_len:
                out.append((pos, ca))
            pos = max(pos, cb)
        if b - pos >= min_len:
            out.append((pos, b))
    return out


class SourceTranscript:
    """Words of one rush file in source seconds, and the source ranges they cover."""

    def __init__(self, path: Path, model_name: str, language: str):
        self.path = path
        size = path.stat().st_size if path.exists() else 0
        # name + size, not the full path: the cache survives moving the rushes to another drive
        ident = hashlib.sha1(f"{path.name.lower()}|{size}|{model_name}|{language}".encode()).hexdigest()
        self.file = CACHE_DIR / f"{ident}.json"
        self.covered: list[tuple[float, float]] = []
        self.words: list[Word] = []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            self.covered = [tuple(r) for r in data["covered"]]
            self.words = [Word(**w) for w in data["words"]]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def missing(self, ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return _subtract(_merge(ranges, MERGE_GAP), self.covered)

    def add(self, a: float, b: float, words: list[Word]) -> None:
        """Words heard in source range [a, b]; those already known (seam overlap) are dropped."""
        old = self.covered
        keep = [w for w in words if not any(ca <= (w.start + w.end) / 2 < cb for ca, cb in old)]
        self.words = sorted(self.words + keep, key=lambda w: w.start)
        self.covered = _merge(old + [(a, b)])

    def between(self, a: float, b: float) -> list[Word]:
        return [w for w in self.words if a <= (w.start + w.end) / 2 < b]

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"file": str(self.path), "covered": self.covered,
                                   "words": [asdict(w) for w in self.words]}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.file)


def transcribe_ranges(needs: dict[Path, list[tuple[float, float]]], decode, transcriber: Transcriber) -> dict:
    """{source: SourceTranscript} covering every range in `needs` (source seconds), transcribing
    only what the cache does not hold. decode(path, start, length) -> 16 kHz mono audio."""
    out = {p: SourceTranscript(p, transcriber.model_name, transcriber.language) for p in needs}
    todo = []
    for p, ranges in needs.items():
        for a, b in out[p].missing(ranges):
            todo.append((p, max(0.0, a - OVERLAP), b + OVERLAP))
    known = sum(b - a for p, rs in needs.items() for a, b in _merge(rs)) - sum(b - a for _, a, b in todo)
    if not todo:
        print("  using cached transcripts")
        return out
    total = sum(b - a for _, a, b in todo)
    if known > 1:
        print(f"  {known / 60:.0f} min already transcribed, {total / 60:.0f} min to go")
    done = 0.0
    for p, a, b in todo:
        audio = decode(p, a, b - a)
        b = a + len(audio) / SAMPLE_RATE   # the file may end before b

        def progress(t, base=done):
            print("\r" + f"  transcribing {min(1.0, (base + t) / total):6.1%}", end="", flush=True)

        words = transcriber(audio, progress)
        out[p].add(a, b, [Word(w.text, round(w.start + a, 3), round(w.end + a, 3), w.prob) for w in words])
        out[p].save()   # saved after each stretch: stopping the job loses at most one stretch
        done += b - a
    print("\r" + f"  transcribing {1:6.1%}")
    return out
