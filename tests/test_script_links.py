"""Sourcing parser: links stay attached to their sentence, sentence cut identical to part 1."""

from fauxraccord.sourcing.script import parse_script
from fauxraccord.text import load_sentences

SCRIPT = """---
title: Essai
---
# La révolte

## Intro

Selon [cette enquête](https://www.snes.edu/article/x/) faite en 2026, 70% des lycées manquent de profs. \
Le [volume](https://www.rtl.fr/a) horaire est énorme.

Les [inégalités](https://en.wikipedia.org/wiki/Social_Outburst_(Chile)#Inequality) explosent.

*extrait*

## Suite
Le modèle ne dit pas comment la [crise](https://legrandcontinent.eu/x/ ) se termine.
Et ça donne ça. (page 9).
Les chercheurs ont créé cet indice ([page 23](https://example.org/study.pdf)).

## A virer

Phrase coupée avec un [lien](https://fr.wikipedia.org/wiki/Mai_68).
"""


def test_links_sections_and_notes(tmp_path):
    path = tmp_path / "script.md"
    path.write_text(SCRIPT, encoding="utf-8")
    doc = parse_script(path)
    assert [s.text for s in doc.sentences] == [s.text for s in load_sentences(path)[0]]
    assert doc.title == "Essai"
    assert [(s.title, s.skip) for s in doc.sections] == [
        ("", False), ("Intro", False), ("Suite", False), ("A virer", True)]

    s0, s1, s2, s3 = doc.sentences[:4]
    assert [link.url for link in s0.links] == ["https://www.snes.edu/article/x/"]
    assert [link.anchor for link in s1.links] == ["volume"]
    assert s2.links[0].url == "https://en.wikipedia.org/wiki/Social_Outburst_(Chile)#Inequality"
    assert s0.paragraph == s1.paragraph != s2.paragraph != s3.paragraph
    assert s3.notes == ["extrait"]

    crise = next(s for s in doc.sentences if "crise" in s.text)
    assert crise.text.startswith("Le modèle ne dit pas comment la crise se termine")
    assert crise.links[0].url == "https://legrandcontinent.eu/x/"
    assert any(s.notes == ["page 9"] for s in doc.sentences)
    study = next(s for s in doc.sentences if s.links and s.links[0].page)
    assert study.links[0].page == 23 and study.section == 2
    assert [link.anchor for _, link in doc.links()] == [
        "cette enquête", "volume", "inégalités", "crise", "page 23"]
