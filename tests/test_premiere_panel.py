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
