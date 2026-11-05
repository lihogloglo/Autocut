"""The two local models Moments reads rushes with (ONNX, no torch, downloaded once):

- an image–text model: each frame becomes a vector, and words become vectors in the same space,
  so "a death screen" can be compared to every frame. CLIP ViT-B/32 by default (fast, 224 px);
  jina-clip-v1 is the larger alternative the step-0 test compares it with.
- YAMNet (Google, Apache 2.0, ONNX export by audiomagic): the 521 AudioSet sounds (gunshot,
  explosion, hammer, laughter…) every 0.48 s, straight from the 16 kHz waveform.
"""

from __future__ import annotations

import csv
import os
import threading
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get("APPDATA", Path.home())) / "fauxraccord" / "models"

VISION = {
    "clip": ("Qdrant/clip-ViT-B-32-vision", "Qdrant/clip-ViT-B-32-text"),
    "jina": ("jinaai/jina-clip-v1", "jinaai/jina-clip-v1"),
}
YAMNET_REPO = "audiomagic/yamnet-onnx"
YAMNET_HOP = 0.48      # seconds between YAMNet frames
YAMNET_WIN = 0.96      # seconds each frame hears

_lock = threading.Lock()


def _quiet_hub() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    import warnings
    warnings.filterwarnings("ignore", module="huggingface_hub")


def _hub_file(name: str) -> str:
    """A YAMNet file from the local cache, downloaded only the first time (no network check after)."""
    from huggingface_hub import hf_hub_download
    try:
        return hf_hub_download(YAMNET_REPO, name, cache_dir=str(CACHE), local_files_only=True)
    except Exception:
        return hf_hub_download(YAMNET_REPO, name, cache_dir=str(CACHE))


def _norm(e: np.ndarray) -> np.ndarray:
    e = np.asarray(e, dtype=np.float32)
    return e / np.maximum(np.linalg.norm(e, axis=-1, keepdims=True), 1e-9)


class Vision:
    """Frames and words as unit vectors in one space."""

    def __init__(self, name: str = "clip"):
        self.name = name
        self.image_model, self.text_model = VISION[name]
        self._img = self._txt = None
        self._words: dict[str, np.ndarray] = {}

    def _image(self):
        with _lock:
            if self._img is None:
                _quiet_hub()
                from fastembed import ImageEmbedding
                print(f"  loading the image model {self.image_model}")
                self._img = ImageEmbedding(self.image_model, cache_dir=str(CACHE))
            return self._img

    def _text(self):
        with _lock:
            if self._txt is None:
                _quiet_hub()
                from fastembed import TextEmbedding
                self._txt = TextEmbedding(self.text_model, cache_dir=str(CACHE))
            return self._txt

    @property
    def dim(self) -> int:
        return 512 if self.name == "clip" else 768

    def images(self, frames: list) -> np.ndarray:
        """Unit vectors of PIL images or H×W×3 arrays."""
        if not frames:
            return np.zeros((0, self.dim), np.float32)
        from PIL import Image
        pics = [f if isinstance(f, Image.Image) else Image.fromarray(f) for f in frames]
        model = self._image()
        return _norm(np.array(list(model.embed(pics, batch_size=32))))

    def words(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in texts if t not in self._words]
        if missing:
            model = self._text()
            for t, e in zip(missing, model.embed(missing)):
                self._words[t] = _norm(e)
        return np.array([self._words[t] for t in texts], dtype=np.float32).reshape(len(texts), -1)


class Sounds:
    """AudioSet sounds with YAMNet."""

    def __init__(self):
        self._session = None
        self.classes: list[str] = []

    def _load(self):
        with _lock:
            if self._session is None:
                _quiet_hub()
                import onnxruntime as ort
                print("  loading the sound model YAMNet")
                model = _hub_file("yamnet.onnx")
                opts = ort.SessionOptions()
                opts.log_severity_level = 3
                self._session = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
            self.names()
            return self._session

    def names(self) -> list[str]:
        """The 521 AudioSet names, in score order (only the small class list is read)."""
        if not self.classes:
            _quiet_hub()
            names = _hub_file("yamnet_class_map.csv")
            with open(names, encoding="utf-8") as fh:
                self.classes = [row["display_name"] for row in csv.DictReader(fh)]
        return self.classes

    def scores(self, wave: np.ndarray) -> np.ndarray:
        """[frames, 521] probabilities; frame i hears [i·0.48, i·0.48 + 0.96] s."""
        return self.frames(wave)[0]

    def frames(self, wave: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """([frames, 521] probabilities, [frames, 1024] sound fingerprints), one frame every 0.48 s."""
        session = self._load()
        if len(wave) == 0:
            return np.zeros((0, len(self.classes)), np.float32), np.zeros((0, 1024), np.float32)
        out, embs = [], []
        piece = 16000 * 120    # two minutes at a time: memory stays flat on a 10-minute chunk
        hop = int(16000 * YAMNET_HOP)
        for s in range(0, len(wave), piece):
            w = wave[s: s + piece + int(16000 * (YAMNET_WIN - YAMNET_HOP))]
            sc, emb = session.run(None, {"waveform": np.ascontiguousarray(w, dtype=np.float32)})[:2]
            keep = max(1, -(-min(piece, len(wave) - s) // hop))
            out.append(sc[:keep])
            embs.append(emb[:keep])
        return np.concatenate(out).astype(np.float32), np.concatenate(embs).astype(np.float32)

    def per_second_both(self, wave: np.ndarray, seconds: int) -> tuple[np.ndarray, np.ndarray]:
        """([seconds, 521] strongest score, [seconds, 1024] mean fingerprint, unit length) per second."""
        sc, emb = self.frames(wave)
        tags = np.zeros((seconds, sc.shape[1] if sc.size else len(self.names())), np.float32)
        fp = np.zeros((seconds, 1024), np.float32)
        if sc.size:
            centre = np.arange(len(sc)) * YAMNET_HOP + YAMNET_WIN / 2
            sec = np.minimum(centre.astype(int), seconds - 1)
            np.maximum.at(tags, sec, sc)
            np.add.at(fp, sec, emb)
            fp = _norm(fp)
        return tags, fp

    def per_second(self, wave: np.ndarray, seconds: int) -> np.ndarray:
        """[seconds, 521]: the strongest score among the frames centred in each second."""
        sc = self.scores(wave)
        out = np.zeros((seconds, sc.shape[1] if sc.size else len(self.classes)), np.float32)
        if sc.size:
            centre = np.arange(len(sc)) * YAMNET_HOP + YAMNET_WIN / 2
            sec = np.minimum(centre.astype(int), seconds - 1)
            np.maximum.at(out, sec, sc)
        return out
