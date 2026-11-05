"""Drag from the contact sheet straight into Premiere.

A card dragged out of the planche window becomes a real file drag (CF_HDROP), the same thing
Explorer gives: Premiere imports the file where it is dropped (timeline or project panel). The
file is the full-resolution one in médias/ (library.py): the same file the download button and
the placement use, so nothing is downloaded twice.

Images are fetched into the cache when the pointer rests on a card, so the drag usually starts at
once. Videos take longer: the first drag starts the download, the card says when it is ready to
drag again.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ..i18n import tr
from .library import Library


class Dragger:
    def __init__(self, out: Path):
        self.out = out
        self.lib = Library.of(out)
        self.lock = threading.Lock()
        self.window = None

    def prepare(self, asset_id: str, choice: dict | None = None) -> dict:
        """A hover (images: fetched into the cache) or a card waiting for its download."""
        return self.lib.request(asset_id, choice, keep=False)

    # --- the drag ----------------------------------------------------------------------------

    def drag(self, asset_id: str, choice: dict | None = None) -> dict:
        """Called on mouse-down + move. Images get a few seconds to arrive; videos are only
        started. The OS drag runs only if the button is still held, else it would drop at once."""
        a = self.lib.assets.get(asset_id)
        if not a:
            return {"state": "error", "error": tr("élément inconnu")}
        job = self.lib.wait(asset_id, choice, 0 if a.kind == "video" else 8, keep=True)
        if job["state"] != "ready":
            return job
        effect = drag_files(self.window, [job["path"]]) if self.window else "none"
        if effect == "released":
            return {"state": "ready", "dropped": False}
        dropped = effect not in ("none", "None")
        if dropped:
            self._remember(asset_id, Path(job["path"]))
        return {"state": "ready", "dropped": dropped}

    def _remember(self, asset_id: str, path: Path) -> None:
        """Dragged items: badge on the sheet, and left out when the panel places the selection."""
        with self.lock:
            done = self.dragged()
            try:
                done[asset_id] = path.relative_to(self.out).as_posix()
            except ValueError:
                done[asset_id] = str(path)
            (self.out / "dragged.json").write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")

    def dragged(self) -> dict:
        try:
            return json.loads((self.out / "dragged.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}


def drag_files(window, paths: list[str]) -> str:
    """Native file drag from the pywebview (WinForms) window. 'released' when the mouse button
    is already up; else the drop effect ('Copy', 'None'…)."""
    import clr
    clr.AddReference("System.Windows.Forms")
    from System import Array, Func, String, Type
    from System.Windows.Forms import Control, DataFormats, DataObject, DragDropEffects, MouseButtons

    form = window.native
    result = {"effect": "released"}

    def go():
        if Control.MouseButtons != MouseButtons.Left:
            return
        data = DataObject(DataFormats.FileDrop, Array[String]([str(p) for p in paths]))
        result["effect"] = str(form.DoDragDrop(data, DragDropEffects.Copy | DragDropEffects.Link))

    form.Invoke(Func[Type](go))
    return result["effect"]


class SheetApi:
    """What the planche page may call (window.pywebview.api) when it runs in the FauxRaccord window."""

    def __init__(self, dragger: Dragger, place=None):
        self._d = dragger
        self._place = place

    def place_all(self) -> dict:
        """« Tout placer dans Premiere »: the window downloads what is needed, then asks the panel."""
        return self._place() if self._place else {"ok": False, "message": tr("Ouvrez la planche depuis FauxRaccord.")}

    def drag(self, asset_id: str, choice: dict | None = None) -> dict:
        return self._d.drag(asset_id, choice)

    def prepare(self, asset_id: str, choice: dict | None = None) -> dict:
        return self._d.prepare(asset_id, choice)

    def insert(self, asset_id: str, choice: dict | None = None) -> dict:
        """« → Premiere »: the file at Premiere's playhead, through the panel. Counts as placed by hand,
        like a drag (left out when everything is placed)."""
        from .bridge import insert
        a = self._d.lib.assets.get(asset_id)
        if not a:
            return {"state": "error", "error": tr("élément inconnu")}
        job = self._d.lib.wait(asset_id, choice, 0 if a.kind == "video" else 8, keep=True)
        if job["state"] != "ready":
            return job
        r = insert(job["path"])
        if r["state"] == "sent":
            self._d._remember(asset_id, Path(job["path"]))
        return r

    def insert_state(self, rid: int) -> dict:
        from .bridge import request_state
        return request_state(int(rid))

    def dragged(self) -> dict:
        return self._d.dragged()
