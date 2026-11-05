"""Improvised wording: kept inside its take, never mistaken for a failed take."""

from pathlib import Path

import pytest

from fauxraccord.align import align
from fauxraccord.takes import resolve_takes, split_pieces
from fauxraccord.text import load_sentences
from fauxraccord.transcribe import Word

SCRIPT = ("Le traité de Versailles impose à l'Allemagne des réparations très lourdes, "
          "que beaucoup jugent humiliantes.\n\nPersonne ne mesure alors les conséquences de ce texte.")
VERBATIM = "le traité de Versailles impose à l'Allemagne des réparations très lourdes que beaucoup jugent humiliantes"
NEXT = "personne ne mesure alors les conséquences de ce texte"

CASES = {
    "verbatim": ([VERBATIM], [VERBATIM]),
    "words changed": (["le traité de Versailles impose à l'Allemagne des indemnités vraiment lourdes "
                       "que beaucoup jugent humiliantes"], None),
    "aside inserted": (["le traité de Versailles impose à l'Allemagne et ça c'est vraiment énorme pour l'époque "
                        "des réparations très lourdes que beaucoup jugent humiliantes"], None),
    "ending changed": (["le traité de Versailles impose à l'Allemagne des réparations très lourdes "
                        "et les Allemands le vivent comme une humiliation"], None),
    "reordered": (["à l'Allemagne le traité de Versailles impose des réparations très lourdes "
                   "que beaucoup jugent humiliantes"], None),
    "heavy paraphrase": (["avec Versailles l'Allemagne doit payer des sommes énormes "
                          "et pour beaucoup c'est une humiliation"], None),
    # improvised take, then a verbatim retake: both are alternatives
    "impro then verbatim": (["le traité de Versailles impose à l'Allemagne des réparations très lourdes "
                             "et les Allemands le vivent comme une humiliation", VERBATIM], None),
    # trail-off + restart cue in the same breath, then a clean take
    "failed then restart": (["le traité de Versailles impose à l'Allemagne non attends", VERBATIM], [VERBATIM]),
}


def words_for(phrases: list[str]) -> list[Word]:
    words, t = [], 1.0
    for phrase in phrases + [NEXT]:
        for w in phrase.split():
            words.append(Word(w, round(t, 3), round(t + 0.25, 3), 0.9))
            t += 0.3
        t += 1.5
    return words


@pytest.mark.parametrize("name", CASES)
def test_improvisation(name: str, tmp_path: Path):
    phrases, expected = CASES[name]
    expected = expected or phrases          # default: every attempt is kept whole
    script = tmp_path / "s.md"
    script.write_text(SCRIPT, encoding="utf-8")
    sentences, tokens = load_sentences(script)
    tok_sentence = [s.idx for s in sentences for _ in range(s.length)]
    words = words_for(phrases)
    maps = align(words, tokens)
    pieces, results = resolve_takes(split_pieces(words, maps, tok_sentence, 5), sentences, maps, words)

    kept = [" ".join(words[i].text for p in take for i in p.words) for take in results[0].takes]
    assert kept == expected
    assert [" ".join(words[i].text for p in t for i in p.words) for t in results[1].takes] == [NEXT]
    # nothing improvised leaks out as a separate ADLIB/CHATTER clip, except the restart cue
    loose = [" ".join(words[i].text for i in p.words) for p in pieces if p.sentence is None]
    assert loose == (["non attends"] if name == "failed then restart" else [])
