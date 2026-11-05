"""Multilingual sentence similarity (local ONNX model, ~220 MB, downloaded once).

Used to find the passage of an English page that supports a French sentence, to pick the
right minute of a video from its captions, and to rank image captions."""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import numpy as np

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE = Path(os.environ.get("APPDATA", Path.home())) / "fauxraccord" / "models"

_model = None
_lock = threading.Lock()


def _quiet_hub() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    import warnings
    warnings.filterwarnings("ignore", module="huggingface_hub")


def _get():
    global _model
    with _lock:
        if _model is None:
            _quiet_hub()
            from fastembed import TextEmbedding
            print("  loading the similarity model (downloaded the first time, ~220 MB)")
            _model = TextEmbedding(MODEL, cache_dir=str(CACHE))
        return _model


def embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    model = _get()
    with _lock:
        e = np.array(list(model.embed([t[:1000] for t in texts], batch_size=32)), dtype=np.float32)
    return e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-9)


def similarity(query: str, texts: list[str]) -> np.ndarray:
    """Cosine similarity of `query` against each text (0 for empty texts)."""
    if not texts:
        return np.zeros(0)
    keep = [i for i, t in enumerate(texts) if t and t.strip()]
    out = np.zeros(len(texts))
    if keep:
        e = embed([query] + [texts[i] for i in keep])
        out[keep] = e[1:] @ e[0]
    return out


def numbers(text: str) -> set[str]:
    """Figures in a text, normalised ("1 000" -> "1000", "22,5" -> "22.5")."""
    text = re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", text)
    return {n.replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", text)
            if len(n) > 1 or n not in "0123456789"}


# --- What an image shows (CLIP, ~600 MB, downloaded once) -----------------------------------------
# Text side is English only: queries come from the LLM's "visual" description of the paragraph.

CLIP_TEXT, CLIP_VISION = "Qdrant/clip-ViT-B-32-text", "Qdrant/clip-ViT-B-32-vision"
_clip: dict = {}
_clip_lock = threading.Lock()


def _clip_models():
    with _clip_lock:
        if not _clip:
            _quiet_hub()
            from fastembed import ImageEmbedding, TextEmbedding
            print("  loading the image model (downloaded the first time, ~600 MB)")
            _clip["text"] = TextEmbedding(CLIP_TEXT, cache_dir=str(CACHE))
            _clip["vision"] = ImageEmbedding(CLIP_VISION, cache_dir=str(CACHE))
        return _clip["text"], _clip["vision"]


def image_match(query: str, images: list) -> np.ndarray:
    """CLIP cosine similarity of an English description against PIL images (None -> nan).
    Typical values: ~0.18 unrelated, ~0.25 on topic, 0.30+ a close match."""
    out = np.full(len(images), np.nan)
    keep = [i for i, im in enumerate(images) if im is not None]
    if not keep or not query.strip():
        return out
    text, vision = _clip_models()
    with _clip_lock:
        t = np.array(list(text.embed([query[:300]])), dtype=np.float32)[0]
        v = np.array(list(vision.embed([images[i] for i in keep], batch_size=16)), dtype=np.float32)
    t /= max(np.linalg.norm(t), 1e-9)
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    out[keep] = v @ t
    return out
