"""Word-level transcription with faster-whisper, cached to JSON."""

from __future__ import annotations

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


def transcribe(audio: np.ndarray, *, model_name: str, language: str, device: str,
               compute_type: str) -> list[Word]:
    _add_cuda_dll_dirs()
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(
        audio,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
        condition_on_previous_text=False,
        initial_prompt=DISFLUENT_PROMPT,
        beam_size=5,
    )
    total = len(audio) / SAMPLE_RATE
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            words.append(Word(w.word.strip(), round(w.start, 3), round(w.end, 3), round(w.probability, 3)))
        print(f"\r  transcribing {seg.end / total:6.1%}  ({len(words)} words)", end="", flush=True)
    print()
    return [w for w in words if w.text]


def load_or_transcribe(cache: Path, media: Path, audio_loader, **kwargs) -> list[Word]:
    stat = media.stat()
    key = {"file": str(media), "size": stat.st_size, "mtime": stat.st_mtime,
           "model": kwargs["model_name"], "language": kwargs["language"]}
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key:
            print(f"  using cached transcript {cache.name}")
            return [Word(**w) for w in data["words"]]
    words = transcribe(audio_loader(), **kwargs)
    cache.write_text(json.dumps({"key": key, "words": [asdict(w) for w in words]},
                                ensure_ascii=False, indent=0), encoding="utf-8")
    return words
