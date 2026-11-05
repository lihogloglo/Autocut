"""Synthetic recording with the typical failure modes, checked end to end minus Whisper."""

from pathlib import Path

import numpy as np

from fauxraccord.align import align
from fauxraccord.takes import ADLIB, CHATTER, FAILED, TAKE, resolve_takes, split_pieces
from fauxraccord.text import load_sentences
from fauxraccord.timeline import Options, build_clips
from fauxraccord.transcribe import Word

SCRIPT = """# Chapitre un

Le traité de Versailles est signé en 1919, dans la galerie des Glaces [1].
Il impose à l'Allemagne des réparations très lourdes, que beaucoup jugent humiliantes.

Personne ne mesure alors les conséquences de ce texte sur la décennie suivante.
"""

# (text, pause before in seconds)
SPOKEN = [
    # S1 failed then complete
    ("le traité de Versailles est", 1.0),
    ("euh", 0.3), ("non", 0.5), ("attends", 0.2),
    ("le traité de Versailles est signé en 1919 dans la galerie des glaces", 1.5),
    # S2: mid-sentence restart (pickup)
    ("il impose à l'Allemagne des réparations très", 1.0),
    ("des réparations très lourdes que beaucoup jugent humiliantes", 0.6),
    # off-script ad-lib
    ("et franchement c'est là que tout commence à mal tourner pour l'Europe", 1.2),
    # S3 two complete takes
    ("personne ne mesure alors les conséquences de ce texte sur la décennie suivante", 1.5),
    ("personne ne mesure alors les conséquences de ce texte sur la décennie suivante", 2.0),
]


def make_words() -> list[Word]:
    words, t = [], 0.0
    for phrase, pause in SPOKEN:
        t += pause
        for tok in phrase.split():
            words.append(Word(tok, round(t, 3), round(t + 0.25, 3), 0.9))
            t += 0.3
    return words


def test_pipeline(tmp_path: Path):
    script = tmp_path / "script.md"
    script.write_text(SCRIPT, encoding="utf-8")
    sentences, tokens = load_sentences(script)
    assert [" ".join(s.text.split()[:2]) for s in sentences] == ["Le traité", "Il impose", "Personne ne"]
    assert sentences[0].text.endswith("des Glaces.")

    words = make_words()
    maps = align(words, tokens)
    tok_sentence = [s.idx for s in sentences for _ in range(s.length)]
    pieces = split_pieces(words, maps, tok_sentence, adlib_words=5)
    pieces, results = resolve_takes(pieces, sentences, maps, words)

    summary = [(p.status, p.sentence, p.take, " ".join(words[i].text for i in p.words)) for p in pieces]
    for row in summary:
        print(row)

    r1, r2, r3 = results
    assert len(r1.takes) == 1 and r1.failed == 1
    assert len(r2.takes) == 1 and not r2.incomplete
    # pickup: kept take = first attempt up to "des", then the restart
    kept_s2 = " ".join(words[i].text for p in r2.takes[0] for i in p.words)
    assert kept_s2 == ("il impose à l'Allemagne des réparations très lourdes que beaucoup jugent humiliantes")
    assert len(r3.takes) == 2
    statuses = {s for s, *_ in summary}
    assert ADLIB in statuses and CHATTER in statuses and FAILED in statuses

    env = np.zeros(10_000)
    clips = build_clips(pieces, {TAKE, ADLIB}, words, sentences, env, 1000.0, Options())
    for c in clips:
        print(f"{c.src_in:7.2f}-{c.src_out:7.2f} {c.color:8} {c.label}")
    assert [c.color for c in clips if c.label.startswith("S003")] == ["Iris", "Forest"]
