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
CACHE = Path(os.environ.get("APPDATA", Path.home())) / "autocut" / "models"

_model = None
_lock = threading.Lock()


def _get():
    global _model
    with _lock:
        if _model is None:
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            import warnings
            warnings.filterwarnings("ignore", module="huggingface_hub")
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
