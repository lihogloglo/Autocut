"""Where each script sentence is spoken in any Premiere sequence, by listening to it.

Used when a sequence carries no `Sxxx` markers (an edit cut by hand, a sequence never derushed by
Autocut): its voice track is transcribed (per-rush cache, so usually instant), aligned to the
script, and every take found gives the sentence's time in the sequence.
"""

from __future__ import annotations

from pathlib import Path

from .align import align
from .i18n import tr
from .premiere_xml import PremiereSequence
from .takes import INCOMPLETE, TAKE, resolve_takes, split_pieces
from .text import load_sentences, script_language, set_language
from .transcribe import Transcriber, transcribe_ranges


def sentence_times(sequence_xml: Path, script: Path, sequence: str | None = None, model: str = "large-v3",
                   language: str = "auto", log=print) -> dict[int, tuple[float, float]]:
    """Sentence index -> (start, end) in sequence seconds, for the first take of each sentence."""
    from . import _pick_device
    seq = PremiereSequence.from_file(sequence_xml, sequence)
    language = script_language(script, language)
    set_language(language)
    device, compute_type = _pick_device("auto", "auto")
    transcriber = Transcriber(model_name=model, language=language, device=device, compute_type=compute_type)
    log(tr("  phrases repérées à l'écoute de « {name} »", name=seq.name))
    words = seq.sequence_words(transcribe_ranges(seq.analysis_needs(), seq.decode, transcriber))
    sentences, tokens = load_sentences(script)
    tok_sentence = [s.idx for s in sentences for _ in range(s.length)]
    maps = align(words, tokens)
    pieces, _ = resolve_takes(split_pieces(words, maps, tok_sentence, 5), sentences, maps, words)
    where: dict[int, tuple[float, float]] = {}
    for p in sorted(pieces, key=lambda p: words[p.words[0]].start):
        if p.sentence is not None and p.status in (TAKE, INCOMPLETE) and p.sentence not in where:
            where[p.sentence] = (words[p.words[0]].start, words[p.words[-1]].end)
    return where
