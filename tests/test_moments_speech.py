"""Moments › what is said: transcribed once per rush (cached, resumable), searched, a "said" signal."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from fauxraccord import gui, transcribe
from fauxraccord.media import ensure_ffmpeg
from fauxraccord.moments import Project, rules, speech
from fauxraccord.moments.index import RushIndex, Settings
from fauxraccord.moments.rules import MomentType, Signals, describe, find
from fauxraccord.transcribe import Word

NAMES = ["Speech", "Gunshot, gunfire"]
# (absolute time, word) said in the test rush
SCRIPT = [(3.0, "Ok,"), (3.4, "on"), (3.7, "raid"), (4.1, "là."), (14.0, "J'suis"), (14.5, "mort."),
          (22.0, "Il"), (22.2, "est"), (22.4, "où"), (22.6, "le"), (22.8, "mec"), (23.0, "?"),
          (33.0, "Je"), (33.2, "suis"), (33.5, "MORT"), (33.9, "encore"), (41.0, "Déjà"), (41.5, "fini.")]


class FakeSounds:
    def names(self):
        return NAMES

    def per_second_both(self, wave, seconds):
        return np.zeros((seconds, len(NAMES)), np.float32), np.zeros((seconds, 1024), np.float32)


class FakeVision:
    name, dim = "clip", 3

    def images(self, frames):
        e = np.ones((len(frames), 3), np.float32)
        return e / np.linalg.norm(e, axis=1, keepdims=True)

    def words(self, texts):
        return np.tile(np.array([[1, 0, 0]], np.float32), (len(texts), 1))


class FakeTranscriber:
    """Says SCRIPT: the audio it gets holds its own time (see `clock_audio`), so it knows where it is."""
    model_name, language = "large-v3", None

    def __init__(self, fail_after: int | None = None):
        self.calls, self.seconds, self.fail_after = 0, 0.0, fail_after

    def __call__(self, audio, progress=None):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise RuntimeError("stopped")
        self.calls += 1
        a = float(audio[0])
        b = a + len(audio) / 16000
        self.seconds += b - a
        if progress:
            progress(b - a)
        return [Word(w, round(t - a, 3), round(t - a + 0.2, 3), 0.9) for t, w in SCRIPT if a <= t < b]


def clock_audio(rec, track, start, length):
    """reader.audio stand-in: each sample is its time in the rush."""
    n = int(round(min(length, rec.duration - start) * 16000))
    return (start + np.arange(n) / 16000).astype(np.float32)


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> Path:
    ensure_ffmpeg()
    out = tmp_path_factory.mktemp("rush") / "Session parlée.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:size=160x90:rate=10:duration=50",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=50", "-c:v", "libx264", "-g", "10",
                    "-preset", "ultrafast", "-c:a", "aac", str(out)], check=True)
    return out


@pytest.fixture()
def env(video, tmp_path, monkeypatch):
    """A built index under tmp, transcripts cached under tmp, the clock audio, small stretches."""
    monkeypatch.setattr(transcribe, "CACHE_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(speech.reader, "audio", clock_audio)
    monkeypatch.setattr(speech, "STRETCH", 20.0)
    monkeypatch.setattr(rules, "_SOUND_NAMES", NAMES)
    speech._MEMO.clear()
    root = tmp_path / "index"
    ix = RushIndex(video, root)
    ix.build(Settings(chunk=30, width=160), FakeVision(), FakeSounds())
    return ix, root


# --- searching -------------------------------------------------------------------------------

def W(text: str, t0: float = 0.0) -> list[Word]:
    return [Word(w, t0 + i, t0 + i + 0.5, 0.9) for i, w in enumerate(text.split())]


def test_norm_drops_accents_case_and_apostrophes():
    assert speech.norm("J'suis DÉJÀ là-bas, œuf") == ["j", "suis", "deja", "la", "bas", "oeuf"]


def test_phrases_are_found_whatever_the_accents_and_case():
    ws = W("bon bah raid réussi encore une fois et là je suis Mort .")
    hits = speech.find_in(ws, "raid reussi")
    assert [(h["start"], h["match"]) for h in hits] == [(2.0, "raid réussi")]
    assert speech.find_in(ws, "je suis mort")[0]["start"] == 9.0
    assert "raid réussi" in hits[0]["text"] and hits[0]["text"].startswith("bon")


def test_small_spelling_differences_are_forgiven():
    ws = W("dans la save zone puis j' suis mort direct et des headshots")
    assert speech.find_in(ws, "safe zone")[0]["start"] == 2.0          # whisper's spelling
    assert speech.find_in(ws, "je suis mort")[0]["start"] == 5.0       # "j' suis" for "je suis"
    assert speech.find_in(W("je suis pas mort"), "je suis mort") == []  # not a word more
    assert speech.find_in(ws, "headshot")[0]["match"] == "headshots"   # plural
    assert speech.find_in(ws, "zombie") == []


def test_short_words_must_be_exact_and_hits_do_not_overlap():
    ws = W("on va le faire on y va on")
    assert len(speech.find_in(ws, "on")) == 3
    assert speech.find_in(ws, "ont") == []
    assert len(speech.find_in(ws, "on y va")) == 1


def test_whisper_word_pieces_are_joined_back():
    ws = [Word("Je", 0, .2, 1), Word("viens", .2, .4, 1), Word("d", .4, .5, 1), Word("'ici.", .5, .7, 1),
          Word("Peut", .8, 1, 1), Word("-être", 1, 1.2, 1)]
    assert speech.join(ws) == "Je viens d'ici. Peut-être"
    assert speech.find_in(ws, "d'ici")[0]["match"] == "d'ici."


# --- transcribing ----------------------------------------------------------------------------

def test_a_rush_is_transcribed_once_in_stretches(env):
    ix, root = env
    assert not speech.done(ix) and speech.words(ix) == [] and speech.status(ix) == {"done": False, "words": 0}
    fake = FakeTranscriber()
    speech.transcribe(ix, fake, root=root, log=lambda *a, **k: None)
    assert fake.calls == 3                                        # 50 s in 20 s stretches
    said = [w.text for w in speech.words(ix)]
    assert said == [w for _, w in SCRIPT]                         # once each, even on the seams
    assert speech.status(ix) == {"done": True, "words": len(SCRIPT)}
    assert (ix.dir / "speech.json").exists()
    again = FakeTranscriber()
    speech.transcribe(ix, again, root=root, log=lambda *a, **k: None)
    assert again.calls == 0                                       # cached
    hits = speech.search(ix, "je suis mort")
    assert [round(h["start"]) for h in hits] == [14, 33]


def test_a_stopped_transcription_goes_on_where_it_stopped(env):
    ix, root = env
    with pytest.raises(RuntimeError):
        speech.transcribe(ix, FakeTranscriber(fail_after=1), root=root, log=lambda *a, **k: None)
    assert not speech.done(ix)
    rest = FakeTranscriber()
    speech.transcribe(ix, rest, root=root, log=lambda *a, **k: None)
    assert rest.calls == 2 and rest.seconds < 35
    assert [w.text for w in speech.words(ix)] == [w for _, w in SCRIPT]


def test_the_track_with_the_most_speech_is_read(env, monkeypatch):
    ix, _ = env
    assert speech.track_for(ix) == 0                              # one track
    monkeypatch.setattr(RushIndex, "audio_tracks", property(lambda self: 2))
    tags = {0: np.zeros((50, 2), np.float32), 1: np.zeros((50, 2), np.float32)}
    tags[1][10:30, 0] = 0.9                                       # the mic track
    monkeypatch.setattr(RushIndex, "tags", lambda self, k: tags[k])
    assert speech.track_for(ix) == 1
    assert speech.label("large-v3", 1) != speech.label("large-v3", 0) == "large-v3"


# --- the "said" signal -----------------------------------------------------------------------

def said_kind(phrases, **kw) -> MomentType:
    return MomentType("u-said", "Dit", mode="event", signals=[{"said": phrases, "window": 3}],
                      before=2, after=2, gap=3, min_len=1, user=True, **kw)


def test_said_signal_is_unknown_until_the_speech_is_read(env):
    ix, root = env
    x, thr, unit = Signals(ix).value({"said": ["je suis mort"]})
    assert np.isnan(x).all() and thr == 0.5 and unit == "said"
    assert find([ix], [said_kind(["je suis mort"])]) == []       # and nothing is transcribed for it


def test_said_signal_marks_the_seconds_around_the_phrase(env):
    ix, root = env
    speech.transcribe(ix, FakeTranscriber(), root=root, log=lambda *a, **k: None)
    x, _, _ = Signals(ix).value({"said": ["je suis mort", "on raid"], "window": 3})
    on = set(np.flatnonzero(x > 0.5))
    assert {2, 3, 4, 13, 14, 15, 32, 33, 34} <= on and not on & {8, 20, 25, 45}
    found = find([ix], [said_kind(["je suis mort"])])
    assert [round(m.anchor) for m in found] == [12, 31]
    for sens in (0.0, 1.0):                                       # the sensitivity cannot flip a word said
        assert len(find([ix], [said_kind(["je suis mort"], sensitivity=sens)])) == 2


def test_describe_shows_said_as_a_tag():
    assert describe({"said": ["on raid"], "window": 3}) == {"read": "said", "words": ["on raid"], "negate": False,
                                                             "box": None}
    assert describe({"opposite": {"said": ["gg"]}})["negate"] is True
    assert describe({"zone": [0, 0, .1, .1], "side": "left", "below": 0.3})["read"] == "gauge"   # zones as before
    assert describe({"sound": ["Speech"]}) is None
    assert said_kind([]).ready() is False and said_kind(["gg"]).ready() is True


# --- the window ------------------------------------------------------------------------------

@pytest.fixture()
def api(env, video, tmp_path, monkeypatch):
    ix, root = env
    monkeypatch.setattr(gui, "APPDATA", tmp_path / "appdata")
    monkeypatch.setattr(gui, "STATE_FILE", tmp_path / "appdata" / "app.json")
    monkeypatch.setattr(gui, "_moments_index", lambda p: RushIndex(Path(p), root))
    a = gui.Api()
    a._state["moments"] = {"rushes": [str(video)]}
    a.ran = []
    monkeypatch.setattr(a, "run", lambda step: a.ran.append(step) or {"ok": True})
    return a


def test_window_search_and_a_kind_made_of_words(api, env, video):
    ix, root = env
    r = api.moments_said("je suis mort")
    assert r["unread"] == 1 and r["total"] == 0 and r["rushes"][0]["done"] is False
    speech.transcribe(ix, FakeTranscriber(), root=root, log=lambda *a, **k: None)
    r = api.moments_said("je suis mort, on raid")
    assert r["unread"] == 0 and [round(h["start"]) for h in r["rushes"][0]["hits"]] == [3, 14, 33]
    k = api.moments_said_kind("je suis mort, on raid")
    assert k["ok"] and k["kind"] == "u-je-suis-mort" and k["total"] == 3 and api.ran == ["moments"]
    proj = Project(api._mo_file())
    kind = next(t for t in proj.types if t.id == "u-je-suis-mort")
    assert kind.user and kind.signals == [{"said": ["je suis mort", "on raid"], "window": 3}]
    assert kind.color in gui.Api.MO_COLOURS and kind.name == "Je suis mort…"
    again = api.moments_said_kind("je suis mort, on raid")       # the same words: the same kind
    assert again["kind"] == "u-je-suis-mort" and len(Project(api._mo_file()).types) == len(proj.types)
    assert api.moments_said_kind("  ")["ok"] is False


def test_window_view_says_whether_the_speech_is_read(api, env, monkeypatch):
    ix, root = env
    monkeypatch.setattr(gui.Api, "_thumb", lambda self, p: "")
    monkeypatch.setattr(gui.Api, "_src_url", lambda self, *a: "")
    api._thumbs = type("S", (), {"server_address": ("127.0.0.1", 1)})()
    monkeypatch.setattr("fauxraccord.moments.view._curves", lambda ix, types: [])
    assert api.moments_view()["rushes"][0]["speech"] == {"done": False, "words": 0}
    speech.transcribe(ix, FakeTranscriber(), root=root, log=lambda *a, **k: None)
    assert api.moments_view()["rushes"][0]["speech"] == {"done": True, "words": len(SCRIPT)}


def test_a_first_word_dated_long_before_the_rest_does_not_stretch_the_hit():
    ws = [Word("Oh", 415.3, 415.5, .9), Word("my", 437.0, 437.2, .9), Word("god.", 437.2, 437.4, .9)]
    [h] = speech.find_in(ws, "oh my god")
    assert (h["start"], h["end"]) == (437.0, 437.4)
