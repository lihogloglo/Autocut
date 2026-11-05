"""Music and ambiences for a script, on request: parts from the AI, searched on Epidemic, redone one at a time."""

import numpy as np
import pytest

from fauxraccord.sfx import board as B
from fauxraccord.sfx import suggest as S

SCRIPT = """# La révolte

## Paris, 1789

Le pain manque dans les faubourgs. Les femmes marchent sur Versailles. La foule gronde devant les grilles.

## Aujourd'hui

Les historiens se disputent encore. Que reste-t-il de cette colère ? Une idée, peut-être.
"""


class FakeEpi:
    def __init__(self):
        self.calls = []

    def search_music(self, term, n=30, bpm=None):
        self.calls.append(("music", term, bpm))
        return [{"uid": f"{term}-{i}", "title": f"{term} {i}", "artist": "A", "bpm": 90, "dur": 120.0,
                 "preview": "", "tags": [], "stems": []} for i in range(3)]

    def search(self, term, kind, n=12, max_ms=6000, min_ms=None):
        self.calls.append(("sfx", term, min_ms))
        from fauxraccord.sfx.library import Snd
        return [Snd(f"epidemic:{term}-{i}", "epidemic", kind, f"{term} {i}", dur=60.0) for i in range(2)]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    script = tmp_path / "revolte.md"
    script.write_text(SCRIPT, encoding="utf-8")
    monkeypatch.setattr(S, "_engine", lambda ctx: "fake")
    return {"script": str(script), "derush": "", "edit": "", "out": str(tmp_path / "revolte - sons")}


def answer(cues):
    return lambda engine, layer, doc, lines, brief, extra="": cues


def test_music_parts_are_searched_with_every_query_in_turn(ctx, monkeypatch):
    seen = {}

    def ask(engine, layer, doc, lines, brief, extra=""):
        seen["brief"], seen["ids"] = brief, [x["id"] for x in lines]
        return [{"first": 0, "last": 2, "title": "Faubourgs", "feel": "violoncelle seul",
                 "queries": ["solo cello, sparse", "baroque strings, tense", "  "], "bpm_min": 110, "bpm_max": 70},
                {"first": 3, "last": 99, "title": "Débat", "feel": "pulsation", "queries": ["analog synth pulse"],
                 "bpm_min": 0, "bpm_max": 0}]
    monkeypatch.setattr(S, "_ask", ask)
    epi = FakeEpi()
    block = S.make(ctx, "music", "pas d'orchestre épique", epi)
    assert seen["brief"] == "pas d'orchestre épique"
    a, b = block["cues"]
    assert (a["first"], a["last"], b["last"]) == (0, 2, max(seen["ids"]))        # kept inside the script
    assert a["queries"] == ["solo cello, sparse", "baroque strings, tense"]       # empty query dropped
    assert (a["bpm_min"], a["bpm_max"]) == (70, 110)                                # swapped into order
    assert ("music", "solo cello, sparse", (70, 110)) in epi.calls
    assert [r["title"] for r in a["results"][:3]] == ["solo cello, sparse 0", "baroque strings, tense 0",
                                                      "solo cello, sparse 1"]
    assert a["results"][1]["query"] == "baroque strings, tense"
    assert a["duration"] > 0 and a["start"] is None                                 # no derush: estimated
    assert S.load(B.Path(ctx["out"]))["music"]["brief"] == "pas d'orchestre épique"


def test_ambiences_leave_gaps_and_search_long_sounds(ctx, monkeypatch):
    monkeypatch.setattr(S, "_ask", answer([{"first": 0, "last": 2, "title": "Faubourgs, 1789",
                                            "feel": "foule, pavés", "queries": ["crowd, market, distant"]}]))
    epi = FakeEpi()
    block = S.make(ctx, "amb", "", epi)
    assert len(block["cues"]) == 1 and block["cues"][0]["results"][0]["layer"] == "amb"
    assert epi.calls == [("sfx", "crowd, market, distant", 15000)]


def test_redo_keeps_the_part_and_says_why(ctx, monkeypatch):
    monkeypatch.setattr(S, "_ask", answer([{"first": 0, "last": 5, "title": "A", "feel": "x", "queries": ["q1"],
                                            "bpm_min": 0, "bpm_max": 0}]))
    S.make(ctx, "music", "", FakeEpi())
    asked = {}

    def ask(engine, layer, doc, lines, brief, extra=""):
        asked["extra"] = extra
        return [{"first": 0, "last": 1, "title": "B", "feel": "plus sombre", "queries": ["dark ambient drone"],
                 "bpm_min": 0, "bpm_max": 0}]
    monkeypatch.setattr(S, "_ask", ask)
    c = S.redo(ctx, "music", "m01", "plus sombre", FakeEpi())
    assert "plus sombre" in asked["extra"] and "q1" in asked["extra"]
    assert (c["id"], c["first"], c["last"], c["title"]) == ("m01", 0, 5, "B")
    assert c["instruction"] == "plus sombre"
    c = S.research(ctx, "music", "m01", ["my own query", ""], FakeEpi(), (80, 100))
    assert c["queries"] == ["my own query"] and (c["bpm_min"], c["bpm_max"]) == (80, 100)
    assert S.load(B.Path(ctx["out"]))["music"]["cues"][0]["queries"] == ["my own query"]


def test_loudness_matches_bs1770():
    """A 1 kHz sine at 0 dBFS in one channel reads -3.01 LUFS; 20 dB lower, -23.0."""
    sr = 24000
    t = np.arange(sr * 5) / sr
    y = 0.1 * np.sin(2 * np.pi * 1000 * t)
    assert B.loudness(y, sr) == pytest.approx(-23.0, abs=0.2)
    stereo = np.stack([y, y], axis=1)
    assert B.loudness(stereo, sr) == pytest.approx(-20.0, abs=0.2)
    assert B.loudness(np.zeros(sr), sr) == -70.0


def test_bed_levels_follow_the_mastering_within_the_editors_range():
    assert B.bed_gain("music", -12.5) == -22.5           # Drop Everything: the user put it at -25
    assert B.bed_gain("music", -8.8) == -25.0            # hot master: never lower than -25
    assert B.bed_gain("music", -16.8) == -20.0           # a stem: never higher than -20
    assert B.bed_gain("amb", -29.4) == pytest.approx(-6.6)   # heavy rain: the user put it at -7
    assert B.bed_gain("music", None) is None
