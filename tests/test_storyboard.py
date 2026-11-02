from autocut.storyboard import FACE, _batches, _clean_beats


def beat(first, last, **kw):
    return {"first": first, "last": last, "technique": "3D", "title": "", "see": "", "motion": "", "image_prompt": "",
            "video_prompt": "", "scene": {}, "notes": "", "reuse": "", **kw}


def spans(beats):
    return [(b["first"], b["last"]) for b in beats]


def test_clean_beats_keeps_a_good_cut():
    assert spans(_clean_beats([beat(3, 4), beat(5, 7)], [3, 4, 5, 6, 7])) == [(3, 4), (5, 7)]


def test_clean_beats_fills_gaps_and_drops_overlaps():
    ids = [10, 11, 12, 13, 14, 15]
    raw = [beat(12, 13), beat(10, 10), beat(13, 13), beat(99, 100)]   # gap 11, overlap 13, out of range
    assert spans(_clean_beats(raw, ids)) == [(10, 11), (12, 15)]


def test_clean_beats_starts_at_the_first_sentence():
    assert spans(_clean_beats([beat(2, 3)], [1, 2, 3])) == [(1, 3)]


def test_clean_beats_without_answer_keeps_the_speaker():
    out = _clean_beats([], [4, 5])
    assert spans(out) == [(4, 5)] and out[0]["technique"] == FACE


def test_batches_skip_locked_sentences():
    lines = [{"id": i, "section": "A" if i < 5 else "B", "text": "", "s": 3} for i in range(10)]
    parts = _batches(lines, locked={3, 4})
    assert [[x["id"] for x in p] for p in parts] == [[0, 1, 2], [5, 6, 7, 8, 9]]
