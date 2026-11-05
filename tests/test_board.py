"""The sound board: files sorted into layers, family tiles that draw a new take on every drag."""

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from fauxraccord.sfx import board as B


def write_wav(path: Path, seconds: float, sr: int = 48000, ch: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    y = (np.sin(np.linspace(0, 400 * seconds, int(sr * seconds))) * 8000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.repeat(y, ch).tobytes())
    return path


def test_wav_duration_from_header(tmp_path):
    p = write_wav(tmp_path / "a.wav", 2.5)
    assert B.wav_duration(p) == pytest.approx(2.5, abs=1e-3)
    (tmp_path / "b.wav").write_bytes(b"ID3 not a wav")
    assert B.wav_duration(tmp_path / "b.wav") is None


@pytest.mark.parametrize("stem,dirs,dur,want", [
    # the user's Epidemic downloads, as their site names them
    ("ES_Swooshes, Whoosh, Low, Short 02 - Epidemic Sound", ["sfx"], 1.4, ("sfx", "whoosh")),
    ("ES_Swooshes, Whoosh, WInd, Cool, Short 02 - Epidemic Sound", ["sfx"], 2.0, ("sfx", "whoosh")),
    ("ES_Objects, Misc, Mains Power, Switch On - Epidemic Sound", ["sfx"], 0.8, ("sfx", "click")),
    ("ES_Communications, Static, Television, Buzz, Noise 03 - Epidemic Sound", ["sfx"], 4.0, ("sfx", "other")),
    ("164982_Crank, Fastening, Metal, Single, Small 02", ["New folder", "sfx"], 1.2, ("sfx", "other")),
    ("ES_Ambience, City, Street, Traffic, Distant - Epidemic Sound", ["sfx"], 95.0, ("amb", "")),
    ("ES_Nature, Rain, Light, Forest - Epidemic Sound", ["sfx"], 60.0, ("amb", "")),
    ("ES_Wood, Friction, Frictioning Two MDF Wood Pieces, Long 03 - Epidemic Sound", ["sfx"], 31.0, ("amb", "")),
    ("ES_Absent-Minded - Calm Shores", ["musiques"], 150.0, ("music", "")),
    ("ES_Christmas, Innit - Dyalla", ["musiques"], 140.0, ("music", "")),
    ("ES_8 Money STEMS BASS", ["ES_8 Money - Giants' Nest", "Epidemic sound"], 160.0, ("music", "")),
    ("ES_The Connection - Lennon Hutton", ["downloads"], 180.0, ("music", "")),
    ("Crowd Aww Sound Effect", ["Epidemic sound", "00 - Musique"], 4.0, ("sfx", "other")),
    ("room tone salon", ["prises"], 40.0, ("amb", "")),
    ("long unnamed thing", ["misc"], 200.0, ("music", "")),
    # the nearest telling folder decides, wherever the added folder starts
    ("Grieg_ Peer Gynt Suite No. 1, Op. 46_ No. 4, In the Hall of the Mountain King",
     ["Epidemic sound", "00 - Musique", "Dirtybiology"], 175.0, ("music", "")),
    ("Sunshine Rain", ["Epidemic sound", "00 - Musique"], 243.0, ("music", "")),
    ("Bee Recorded Individually 05", ["New folder", "sfx", "epidemic sound", "Futur vulga"], 206.0, ("amb", "")),
    ("ES_Designed, Riser, Sci-Fi 07 - Epidemic Sound", ["sfx"], 9.7, ("sfx", "riser")),
    ("ES_Bomb, Explosion, Small, Bang, Detonation 02 - Epidemic Sound", ["sfx"], 2.7, ("sfx", "hit")),
    ("ES_Sunrise Chime", ["sfx"], 1.5, ("sfx", "pop")),
    ("ES_Taxi Brazil - Speedy The Spider", ["New folder", "sfx"], 148.3, ("music", "")),
])
def test_classify_real_names(stem, dirs, dur, want):
    assert B.classify(stem, dirs, dur) == want


def test_music_meta_and_tidy():
    assert B.music_meta("ES_The Connection - Lennon Hutton") == ("The Connection", "Lennon Hutton", "")
    assert B.music_meta("ES_8 Money STEMS BASS") == ("8 Money", "", "bass")
    assert B.music_meta("ES_Hang - Viriya (8484d52a)") == ("Hang", "Viriya", "")
    assert B.tidy("ES_Swooshes, Whoosh, Low - Epidemic Sound") == "Swooshes, Whoosh, Low"
    assert B.tidy("164982_Crank, Fastening") == "Crank, Fastening"


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "SETTINGS", tmp_path / "board.json")
    monkeypatch.setattr(B, "INDEX", tmp_path / "index.json")
    monkeypatch.setattr(B.L, "earshot_ok", lambda: False)
    lib = tmp_path / "lib"
    for i in range(4):
        write_wav(lib / "sfx" / f"Whoosh {i}.wav", 0.6)
    write_wav(lib / "sfx" / "Click 1.wav", 0.2)
    write_wav(lib / "musiques" / "ES_Hang - Viriya.wav", 50, sr=8000, ch=1)
    write_wav(lib / "ambiances" / "Forest night.wav", 25, sr=8000, ch=1)
    media = tmp_path / "proj - sons" / "médias"
    write_wav(media / "earshot" / "swish-s123.wav", 0.5)         # takes rendered for drags: not listed
    b = B.Board(lambda: [str(lib)], lambda: media)
    b.index = B.Index(tmp_path / "index.json")
    return b


def test_catalog_sorts_layers(board):
    c = board.catalog()
    by = {i["name"]: i for i in c["items"]}
    assert by["Whoosh 0"]["layer"] == "sfx" and by["Whoosh 0"]["family"] == "whoosh"
    assert by["ES_Hang - Viriya"]["layer"] == "music" and by["ES_Hang - Viriya"]["artist"] == "Viriya"
    assert by["Forest night"]["layer"] == "amb"
    assert "swish-s123" not in by
    assert c["next"]["whoosh"].startswith("file:") and c["next"]["typing"] is None


def test_tile_draws_every_take_before_repeating(board):
    board.catalog()
    seen = []
    for _ in range(12):
        seen.append(board.peek("whoosh"))
        board.skip("whoosh")
    assert set(seen[:4]) == set(seen[4:8]) == set(board._pool("whoosh"))
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_stars_restrict_the_draw_and_persist(board, tmp_path):
    board.catalog()
    pool = board._pool("whoosh")
    board.pick("whoosh", pool[0], True)
    board.pick("whoosh", pool[2], True)
    draws = set()
    for _ in range(8):
        draws.add(board.skip("whoosh"))
    assert draws == {pool[0], pool[2]}
    saved = json.loads((tmp_path / "board.json").read_text(encoding="utf-8"))
    assert next(t for t in saved["tiles"] if t["id"] == "whoosh")["picks"] == [pool[0], pool[2]]
    board.pick("whoosh", pool[0], False)
    assert board.skip("whoosh") == pool[2]


def test_long_takes_stay_out_of_the_draw_unless_starred(board, tmp_path):
    write_wav(tmp_path / "lib" / "sfx" / "Whoosh long flames.wav", 9.0, sr=8000, ch=1)
    board.catalog()
    long_id = next(i for i, it in board.items.items() if it["name"] == "Whoosh long flames")
    assert long_id not in board._pool("whoosh") and len(board._pool("whoosh")) == 4
    board.pick("whoosh", long_id, True)
    assert board._pool("whoosh") == [long_id]


def test_chosen_take_stays(board):
    board.catalog()
    pick = board._pool("whoosh")[1]
    board.choose("whoosh", pick)
    assert board.peek("whoosh") == pick == board.peek("whoosh")


def test_waves_and_allowed(board, tmp_path):
    c = board.catalog()
    ids = [i["id"] for i in c["items"]]
    w = board.waves(ids)
    assert set(w) == set(ids)
    assert len(w[ids[0]]["wave"]) == 160
    assert board.allowed(Path(c["items"][0]["path"]))
    assert not board.allowed(tmp_path / "elsewhere.wav")


def test_starting_tiles_and_old_stars(tmp_path, monkeypatch):
    """A new board starts with the six tiles; stars given to sound effects before tiles existed join them."""
    settings = tmp_path / "board.json"
    monkeypatch.setattr(B, "SETTINGS", settings)
    monkeypatch.setattr(B.L, "earshot_ok", lambda: False)
    lib = tmp_path / "lib"
    star = write_wav(lib / "sfx" / "Whoosh 9.wav", 0.5)
    settings.write_text(json.dumps({"stars": [f"file:{star}", "file:elsewhere.wav"]}), encoding="utf-8")
    b = B.Board(lambda: [str(lib)], lambda: tmp_path / "media")
    b.index = B.Index(tmp_path / "index.json")
    assert [t["label"] for t in b.settings["tiles"]] == ["Whoosh", "Clic", "Pop", "Clavier", "Impact", "Montée"]
    assert b.tile("riser")["query"] == "riser"                 # Epidemic is searched in English
    b.catalog()
    assert b.tile("whoosh")["picks"] == [f"file:{star}"] and b.settings["stars"] == ["file:elsewhere.wav"]


class FakeEpi:
    def search(self, term, kind, n=12, max_ms=6000, min_ms=None):
        from fauxraccord.sfx.library import Snd
        self.term = term
        return [Snd(f"epidemic:{term}-{i}", "epidemic", kind, f"{term} {i}", dur=1.0) for i in range(3)]


def test_a_search_becomes_a_tile(board, tmp_path):
    write_wav(tmp_path / "lib" / "sfx" / "ES_Paper Slide, Movement.wav", 0.7)
    write_wav(tmp_path / "lib" / "sfx" / "Paper Crumple Big.wav", 0.9)
    board.catalog()
    t = board.create_tile("Papier", "paper")
    assert t["id"] == "u-papier" and board.create_tile("Papier", "paper")["id"] == "u-papier-2"
    assert len(board.members(t)) == 2                          # the files whose names have its words
    epi = FakeEpi()
    board._epi = epi
    board.search_tile("u-papier")
    assert epi.term == "paper"
    c = board.catalog()
    assert len(c["members"]["u-papier"]) == 5 and c["next"]["u-papier"] in c["members"]["u-papier"]
    local = [i for i in c["members"]["u-papier"] if i.startswith("file:")]
    assert set(board._pool("u-papier")) == set(local)           # random draws: own files before downloads
    board.pick("u-papier", "epidemic:paper-1", True)
    assert board._pool("u-papier") == ["epidemic:paper-1"]
    board.update_tile("u-papier", {"label": "Papiers", "query": "paper rustle"})
    assert board.tile("u-papier")["label"] == "Papiers"
    board.delete_tile("u-papier")
    assert board.tile("u-papier") is None and "u-papier" not in board.catalog()["next"]
    saved = json.loads((tmp_path / "board.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in saved["tiles"]] == ["whoosh", "click", "pop", "typing", "hit", "riser", "u-papier-2"]
