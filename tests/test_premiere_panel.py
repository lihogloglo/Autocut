"""The Premiere panel: installed without Creative Cloud (copied where Premiere looks), the fauxraccord:// link,
the versions the panel and the app compare, and « → Premiere » (one file at the playhead)."""

import json
import re
import time
from pathlib import Path

import pytest

from fauxraccord.sourcing import bridge

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def uxp(tmp_path, monkeypatch):
    """A fake %APPDATA% with Premiere's list of panels: someone else's panel, and the panel's old id."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(bridge, "premiere_installed", lambda: True)
    monkeypatch.setattr(bridge, "premiere_running", lambda: False)
    ext = tmp_path / "Adobe" / "UXP" / "Plugins" / "External"
    for d in ("com.other.tool_1.0.0", "com.lihogloglo.autocut_0.1.0"):
        (ext / d).mkdir(parents=True)
        (ext / d / "manifest.json").write_text("{}")
    reg = tmp_path / "Adobe" / "UXP" / "PluginsInfo" / "v1" / "premierepro.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(json.dumps({"plugins": [
        {"name": "Other", "path": "$localPlugins\\External\\com.other.tool_1.0.0", "pluginId": "com.other.tool",
         "status": "enabled", "type": "uxp", "versionString": "1.0.0", "hostMinVersion": "25.0.0"},
        {"name": "Autocut", "path": "$localPlugins\\External\\com.lihogloglo.autocut_0.1.0",
         "pluginId": "com.lihogloglo.autocut", "status": "enabled", "type": "uxp", "versionString": "0.1.0",
         "hostMinVersion": "25.6.0"}]}))
    return tmp_path


def test_panel_version_is_the_manifest_version():
    m = json.loads((ROOT / "premiere" / "manifest.json").read_text(encoding="utf-8"))
    js = (ROOT / "premiere" / "index.js").read_text(encoding="utf-8")
    assert re.search(r'const VERSION = "([^"]+)"', js).group(1) == m["version"]
    assert "fauxraccord" in m["requiredPermissions"]["launchProcess"]["schemes"]
    assert m["id"] == "com.lihogloglo.fauxraccord"


def test_install_copies_the_panel_and_replaces_the_old_one(uxp):
    m = bridge.panel_manifest()
    assert bridge.panel_state() == (True, False, False)
    assert bridge.install_panel(log=lambda *_: None)
    reg = json.loads((uxp / "Adobe/UXP/PluginsInfo/v1/premierepro.json").read_text(encoding="utf-8"))
    ids = [p["pluginId"] for p in reg["plugins"]]
    assert ids == ["com.other.tool", m["id"]]                      # someone else's panel kept, the old id gone
    ours = reg["plugins"][1]
    assert ours["path"] == f"$localPlugins\\External\\{m['id']}_{m['version']}" and ours["status"] == "enabled"
    ext = uxp / "Adobe/UXP/Plugins/External"
    assert not (ext / "com.lihogloglo.autocut_0.1.0").exists() and (ext / "com.other.tool_1.0.0").exists()
    assert (ext / f"{m['id']}_{m['version']}" / "index.js").read_bytes() == (bridge.PANEL / "index.js").read_bytes()
    assert bridge.panel_state() == (True, True, True)

    stamp = (uxp / "Adobe/UXP/PluginsInfo/v1/premierepro.json").stat().st_mtime_ns
    assert bridge.install_panel(log=lambda *_: None)               # same version: nothing rewritten
    assert (uxp / "Adobe/UXP/PluginsInfo/v1/premierepro.json").stat().st_mtime_ns == stamp

    assert bridge.uninstall_panel(log=lambda *_: None)
    reg = json.loads((uxp / "Adobe/UXP/PluginsInfo/v1/premierepro.json").read_text(encoding="utf-8"))
    assert [p["pluginId"] for p in reg["plugins"]] == ["com.other.tool"]
    assert not (ext / f"{m['id']}_{m['version']}").exists()


def test_changed_files_count_as_a_new_version(uxp):
    m = bridge.panel_manifest()
    bridge.install_panel(log=lambda *_: None)
    (uxp / "Adobe/UXP/Plugins/External" / f"{m['id']}_{m['version']}" / "index.js").write_text("// older")
    assert bridge.panel_state() == (True, True, False)


def test_an_unreadable_list_is_left_alone(uxp):
    reg = uxp / "Adobe/UXP/PluginsInfo/v1/premierepro.json"
    reg.write_text("{not json")
    notes = []
    assert not bridge.install_panel(log=notes.append)
    assert reg.read_text() == "{not json" and notes


def test_no_premiere_no_install(uxp, monkeypatch):
    monkeypatch.setattr(bridge, "premiere_installed", lambda: False)
    assert not bridge.install_panel(log=lambda *_: None)
    assert bridge.panel_state()[0] is False


def test_entries_outside_the_plugins_folder_are_never_deleted(uxp):
    assert bridge._plugin_dir({"path": "$localPlugins\\External\\..\\..\\..\\.."}) is None
    assert bridge._plugin_dir({"path": ""}) is None
    assert bridge._plugin_dir({"path": "$localPlugins\\External\\x_1"}).name == "x_1"


def test_insert_needs_the_panel_open(tmp_path, monkeypatch):
    f = tmp_path / "S001-01 photo.jpg"
    f.write_bytes(b"x")
    monkeypatch.setitem(bridge._SEEN, "at", 0.0)
    assert bridge.insert(f)["state"] == "error"
    monkeypatch.setitem(bridge._SEEN, "at", time.time())
    r = bridge.insert(f)
    assert r["state"] == "sent"
    assert bridge._REQ["kind"] == "insert"
    assert bridge._REQ["data"] == {"path": str(f), "name": f.name, "audio": False, "image": True, "duration": None}
    assert bridge.request_state(r["id"])["state"] == "waiting"


def test_panel_version_seen(monkeypatch):
    monkeypatch.setitem(bridge._SEEN, "at", time.time())
    monkeypatch.setitem(bridge._SEEN, "version", "0.4.0")
    assert bridge.panel_version() == "0.4.0"
    monkeypatch.setitem(bridge._SEEN, "at", 0.0)
    assert bridge.panel_version() == ""


def test_link_views():
    from fauxraccord.gui import _link_view
    assert _link_view("fauxraccord://start") == "start"
    assert _link_view("fauxraccord://open/sons") == "sons"
    assert _link_view("fauxraccord://open/moments/") == "moments"
    assert _link_view("fauxraccord://open/../../x") == "main"
    assert _link_view("fauxraccord:") == "main"


# --- the panel as a connector: the playhead, the open sequence, seek ------------------------------------------

def test_sentence_under_the_playhead():
    from fauxraccord.sourcing.place import sentence_at
    spans = {0: (1.0, 3.0), 1: (3.5, 6.0), 4: (8.0, 9.0)}
    assert sentence_at(spans, 0.5) is None              # before the first sentence
    assert sentence_at(spans, 2.0) == 0
    assert sentence_at(spans, 3.2) == 0                 # between two: the one just said
    assert sentence_at(spans, 5.9) == 1
    assert sentence_at(spans, 20.0) == 4
    assert sentence_at({}, 2.0) is None


def test_the_open_sequence_gives_the_sentences_by_its_markers():
    from fauxraccord.sourcing.place import spans_from_panel
    seq = {"name": "derush", "fps": 25, "items": [{"start": 0, "end": 20, "in": 0, "path": "C:/r/a.mp4"}],
           "markers": [{"name": "S001", "start": 1.0, "duration": 2.0}, {"name": "S002", "start": 4.0, "duration": 3.0}]}
    spans = spans_from_panel(seq)
    assert set(spans) == {0, 1} and spans[0][0] == pytest.approx(1.0) and spans[1][0] == pytest.approx(4.0)
    assert spans_from_panel({**seq, "markers": []}) == {}


def _serve(monkeypatch, **hooks):
    from http.server import ThreadingHTTPServer
    import threading
    for k, v in hooks.items():
        monkeypatch.setitem(bridge._HOOKS, k, v)
    monkeypatch.setitem(bridge._REQ, "state", "")         # no request left by another test
    server = ThreadingHTTPServer(("127.0.0.1", 0), bridge._Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_the_panel_tells_the_playhead_and_takes_a_seek(monkeypatch):
    import urllib.request
    seen, asked = [], []
    server, url = _serve(monkeypatch, playhead=lambda t, s: seen.append((t, s)),
                         want=lambda s: asked.append(s) or True,
                         status=lambda: {"project": "Révolution", "sentence": "S043"})
    try:
        bridge.seek(12.5)
        with urllib.request.urlopen(url + "/pending?v=0.5.0&t=731.250&seq=derush%20final") as r:
            d = json.loads(r.read())
        assert seen == [(731.25, "derush final")] and asked == ["derush final"]
        assert d["seek"] == 12.5 and d["want"] == "sequence" and d["request"] is None
        assert d["status"] == {"project": "Révolution", "sentence": "S043"}
        with urllib.request.urlopen(url + "/pending?v=0.5.0") as r:       # no playhead (no sequence open)
            d = json.loads(r.read())
        assert d["seek"] is None and d["want"] is None and len(seen) == 1   # a seek is taken once
    finally:
        server.shutdown()


def test_the_panel_sends_the_open_sequence(monkeypatch):
    import urllib.request
    got = []
    server, url = _serve(monkeypatch, sequence=got.append)
    try:
        body = json.dumps({"name": "edit", "items": [], "markers": []}).encode()
        req = urllib.request.Request(url + "/sequence", data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["ok"]
        assert got == [{"name": "edit", "items": [], "markers": []}]
    finally:
        server.shutdown()


def test_the_panel_has_no_buttons_but_start():
    html = (ROOT / "premiere" / "index.html").read_text(encoding="utf-8")
    assert re.findall(r"<sp-(?:action-)?button[^>]*id=\"(\w+)\"", html) == ["start"]
    assert "sp-picker" not in html


def test_planche_calls_reach_the_tab_api_only():
    from fauxraccord.gui import Api

    class Fake:
        def drag(self, x):
            return {"dragged": x}

        def _secret(self):
            return "no"

    api = Api.__new__(Api)
    api._planche = {"sources": {"url": "http://x", "api": Fake(), "out": ""}}
    assert api.planche_call("sources", "drag", ["a1"]) == {"dragged": "a1"}
    assert api.planche_call("sources", "_secret")["state"] == "error"
    assert api.planche_call("storyboard", "drag", ["a1"])["state"] == "error"
    assert api.planche_state() == {"sources": "http://x"}
