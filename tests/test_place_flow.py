"""Placing illustrations: the AI fills the sentences nothing was chosen for; the window asks the Premiere
panel through the bridge; one edit (« Montage ») per project."""

import json
import os
import time

from fauxraccord.sourcing import bridge
from fauxraccord.sourcing.library import auto_picks
from fauxraccord.sourcing.model import Asset


def _a(id, sentence, score, kind="image", rights="libre", origin="recherche"):
    return Asset(id=id, kind=kind, via="commons", origin=origin, sentence=sentence, paragraph=0, score=score, rights=rights)


def test_auto_picks_fill_only_unchosen_sentences():
    assets = [_a("a1", 0, 0.9), _a("a2", 0, 0.5),            # sentence 0: chosen by the user (a2)
              _a("b1", 1, 0.4), _a("b2", 1, 0.8),            # sentence 1: the best is b2
              _a("c1", 2, 0.99, kind="video"),               # videos are the user's choice (their excerpt)
              _a("d1", 3, 0.9, rights="protégé"), _a("d2", 3, 0.2, origin="lien")]
    picks = auto_picks(assets, chosen={"a2"})
    assert set(picks) == {"b2", "d2"}


def test_auto_picks_prefer_cited_links_on_a_tie():
    assert set(auto_picks([_a("x", 0, 0.5), _a("y", 0, 0.5, origin="lien")], set())) == {"y"}


def test_panel_request_lifecycle():
    rid = bridge.request("storyboard")
    assert bridge.request_state(rid)["state"] == "waiting"
    with bridge._REQ_LOCK:
        bridge._REQ["state"] = "done"
        bridge._REQ["message"] = "10 cartes sur V3"
    assert bridge.request_state(rid) == {"state": "done", "message": "10 cartes sur V3", "kind": "storyboard"}
    assert bridge.request_state(rid - 1)["state"] == "gone"          # an older request was replaced
    rid = bridge.request("sources")
    with bridge._REQ_LOCK:
        bridge._REQ["at"] = time.time() - bridge.WAIT - 1
    assert bridge.request_state(rid)["state"] == "expired"          # nobody picked it up


def test_one_edit_per_project(tmp_path):
    from fauxraccord.gui import _unify_montage
    old, new = tmp_path / "derush.fauxraccord.xml", tmp_path / "montage v3.xml"
    old.write_text("<xmeml/>")
    new.write_text("<xmeml/>")
    os.utime(old, (1, 1))
    s = {"place_xml": str(old), "sfx_xml": str(new)}
    _unify_montage(s)
    assert s == {"place_xml": str(new), "sfx_xml": ""}             # the newer sound edit becomes the edit
    s = {"place_xml": str(new), "sfx_xml": str(old)}
    _unify_montage(s)
    assert s == {"place_xml": str(new), "sfx_xml": ""}             # an older one is dropped


def test_coverage_marks_chosen_and_dragged(tmp_path):
    from fauxraccord.sourcing.library import coverage
    man = {"script": "s.md", "title": "T", "sections": [], "errors": [],
           "sentences": [{"idx": i} for i in range(4)],
           "assets": [{"id": "a", "kind": "image", "via": "x", "origin": "lien", "sentence": 1, "paragraph": 0, "score": 1},
                      {"id": "b", "kind": "image", "via": "x", "origin": "lien", "sentence": 2, "paragraph": 0, "score": 1},
                      {"id": "c", "kind": "image", "via": "x", "origin": "lien", "sentence": 3, "paragraph": 0, "score": 1}]}
    (tmp_path / "manifest.json").write_text(json.dumps(man))
    (tmp_path / "selection.json").write_text(json.dumps({"a": {}, "b": {}}))
    (tmp_path / "dragged.json").write_text(json.dumps({"b": "médias/b.jpg"}))
    cov = coverage(tmp_path)
    assert cov["states"] == ["", "c", "p", ""]
    assert cov["auto"] == 1                                          # sentence 3 would get « c »
