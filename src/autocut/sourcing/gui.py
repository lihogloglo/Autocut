"""Illustrations tab: drop the script (+ derush / edit), collect, choose on the contact sheet, place on the edit."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tkinter import ttk
import tkinter as tk

from ..gui import SETTINGS as MAIN_SETTINGS
from ..ui import PAD, DropZone, Fold, JobTab
from . import collect, default_out

LLM = {"Auto (Ollama s'il tourne, sinon Claude si clé, sinon simple)": "auto",
       "Simple (noms propres, dates, mots-clés)": "off", "Ollama (local)": "ollama", "Claude (API, payant)": "claude"}
SHOT_HEIGHTS = {"Écran (1920 × 1080)": 1080, "Haute (3840 × 4800)": 2400, "Très haute (3840 × 7200)": 3600}

SETTINGS = MAIN_SETTINGS.with_name("sources.json")


def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _main_script() -> str:
    try:
        return json.loads(MAIN_SETTINGS.read_text(encoding="utf-8")).get("script", "")
    except (OSError, ValueError):
        return ""


def _existing(p: str) -> str:
    return p if p and Path(p).is_file() else ""


class SourcesTab(JobTab):
    def __init__(self, master):
        super().__init__(master)
        self.settings = _load_settings()
        self.server = None
        self.script = _existing(self.settings.get("script") or _main_script())
        self.derush = _existing(self.settings.get("derush", ""))
        self.edit = _existing(self.settings.get("edit", ""))

        self.zone = DropZone(
            self, "Déposez le script (.md), et si vous les avez le derush et le montage (.xml)",
            self.add, self.rows,
            dialog_types=[("Script ou XML Premiere", "*.md *.txt *.xml"), ("Tous", "*.*")])
        self.zone.pack(fill="x", **PAD)

        opts = Fold(self, "Réglages de la collecte")
        opts.pack(fill="x", **PAD)
        o = opts.inner
        self.shots = tk.BooleanVar(value=self.settings.get("shots", True))
        self.search = tk.BooleanVar(value=self.settings.get("search", True))
        self.web = tk.BooleanVar(value=self.settings.get("web", True))
        self.videos = tk.BooleanVar(value=self.settings.get("videos", True))
        self.llm = tk.StringVar(value=self.settings.get("llm", next(iter(LLM))))
        self.segment = tk.IntVar(value=self.settings.get("segment", 30))
        self.full_max = tk.IntVar(value=self.settings.get("full_max", 10))
        shot_h = self.settings.get("shot_height", "Haute (3840 × 4800)")
        self.shot_height = tk.StringVar(value=shot_h if shot_h in SHOT_HEIGHTS else "Haute (3840 × 4800)")
        ttk.Checkbutton(o, text="Captures des pages", variable=self.shots).grid(row=0, column=0, sticky="w", **PAD)
        ttk.Checkbutton(o, text="Wikimedia, Europeana", variable=self.search).grid(row=0, column=1, sticky="w", **PAD)
        ttk.Checkbutton(o, text="Images du web (droits inconnus)", variable=self.web) \
            .grid(row=0, column=2, sticky="w", **PAD)
        ttk.Checkbutton(o, text="YouTube pour « (extrait …) »", variable=self.videos) \
            .grid(row=0, column=3, sticky="w", **PAD)
        ttk.Label(o, text="Requêtes").grid(row=1, column=0, sticky="w", **PAD)
        ttk.Combobox(o, textvariable=self.llm, values=list(LLM), state="readonly", width=52) \
            .grid(row=1, column=1, columnspan=3, sticky="w", **PAD)
        ttk.Label(o, text="Captures").grid(row=2, column=0, sticky="w", **PAD)
        ttk.Combobox(o, textvariable=self.shot_height, values=list(SHOT_HEIGHTS), state="readonly", width=24) \
            .grid(row=2, column=1, sticky="w", **PAD)
        vid = ttk.Frame(o)
        vid.grid(row=3, column=0, columnspan=4, sticky="w")
        ttk.Label(vid, text="Extrait vidéo (s)").pack(side="left", **PAD)
        ttk.Spinbox(vid, textvariable=self.segment, from_=5, to=300, increment=5, width=5).pack(side="left")
        ttk.Label(vid, text="Vidéo entière si moins de (min)").pack(side="left", **PAD)
        ttk.Spinbox(vid, textvariable=self.full_max, from_=0, to=120, increment=1, width=5).pack(side="left")

        bar = ttk.Frame(self)
        bar.pack(fill="x", **PAD)
        self.steps = [ttk.Button(bar, text="1. Collecter", width=14, command=self.start),
                      ttk.Button(bar, text="2. Choisir", width=14, command=self.open_sheet),
                      ttk.Button(bar, text="3. Placer sur le montage", command=self.place)]
        for k, b in enumerate(self.steps):
            b.pack(side="left", padx=(0 if k == 0 else 6, 0))
        ttk.Button(bar, text="Dossier", style="Toolbutton", command=self.open_folder).pack(side="right")
        self.build_footer()
        self._state = None
        self.refresh_steps()
        self._tick()

    # --- inputs ---------------------------------------------------------------------------
    def add(self, paths: list[Path]) -> None:
        for p in paths:
            if not p.is_file():
                continue
            name = p.name.lower()
            if p.suffix.lower() in (".md", ".txt"):
                self.script = str(p)
            elif name.endswith(".autocut.xml"):
                self.derush = str(p)
            elif p.suffix.lower() == ".xml":
                self.edit = str(p)
        self._save()
        self.refresh_steps()

    def rows(self):
        def clear(attr):
            return lambda: (setattr(self, attr, ""), self._save(), self.refresh_steps())
        return [("Script", self.script, clear("script")),
                ("Derush", self.derush, clear("derush")),
                ("Montage", self.edit, clear("edit"))]

    def take_derush(self, xml: Path, script: Path | None) -> None:
        """The derush tab finished: use its XML (and its script when none is set here)."""
        self.derush = str(xml)
        if script and script.suffix.lower() in (".md", ".txt") and not self.script:
            self.script = str(script)
        self._save()
        self.zone.refresh()
        self.refresh_steps()

    def _save(self) -> None:
        _save_settings({"script": self.script, "derush": self.derush, "edit": self.edit,
                        "shots": self.shots.get(), "search": self.search.get(), "web": self.web.get(),
                        "videos": self.videos.get(), "llm": self.llm.get(), "shot_height": self.shot_height.get(),
                        "segment": self.segment.get(), "full_max": self.full_max.get()})

    def _out(self) -> Path | None:
        return default_out(Path(self.script)) if self.script else None

    def _progress(self) -> tuple[bool, bool, bool, bool]:
        out = self._out()
        return (bool(out and (out / "manifest.json").exists()), bool(out and (out / "selection.json").exists()),
                bool(out and (out / "export").is_dir()), bool(self.derush or self.edit))

    def _tick(self) -> None:
        """The contact sheet works in the browser: notice when it saved a selection or exported."""
        if not self.running and self._progress() != self._state:
            self.refresh_steps()
        self.after(2000, self._tick)

    def refresh_steps(self) -> None:
        """Highlight the next step and say in one line what it does."""
        if not hasattr(self, "steps") or self.running:
            return
        self._state = self._progress()
        collected, chosen, exported, xml = self._state
        nxt = 0 if not collected else 1 if not chosen or not xml else 2
        for k, b in enumerate(self.steps):
            b.configure(style="Accent.TButton" if k == nxt else "TButton")
            b["state"] = "normal" if (k == 0 and self.script) or (k == 1 and collected) or (k == 2 and chosen and xml) \
                else "disabled"
        if not self.script:
            msg = "Le script suffit ; le derush et le montage servent à placer les images aux bons timecodes."
        elif not collected:
            msg = "Collecter : images des liens, captures des pages, recherches (quelques minutes, mis en cache)."
        elif not chosen or not exported:
            msg = "Choisir : cliquez les vignettes à garder dans la planche, puis « Exporter la sélection »."
        elif not xml:
            msg = "Exporté (dossier « export »). Pour les timecodes, déposez le derush ou le montage (.xml)."
        else:
            msg = ("Après chaque nouveau montage : Fichier > Exporter > Final Cut Pro XML, déposez-le, "
                   "puis « 3. Placer ».")
        self.set_status(msg)

    # --- steps ------------------------------------------------------------------------------
    def on_busy(self, busy: bool) -> None:
        for b in self.steps:
            b["state"] = "disabled" if busy else "normal"
        if not busy:
            self.refresh_steps()

    def start(self) -> None:
        script = Path(self.script)
        self._save()
        kwargs = dict(shots=self.shots.get(), search=self.search.get(), web=self.web.get(), videos=self.videos.get(),
                      llm=LLM.get(self.llm.get(), "auto"), seg_len=float(self.segment.get()),
                      full_video_max=float(self.full_max.get()) * 60,
                      shot_height=SHOT_HEIGHTS[self.shot_height.get()],
                      log=lambda t: self.write(t + "\n"))
        self.run_job("collect", lambda: collect(script, **kwargs))

    def place(self) -> None:
        from .export import export
        out, derush, edit = self._out(), self.derush, self.edit
        self._save()
        log = lambda t: self.write(t + "\n")   # noqa: E731
        self.run_job("place", lambda: export(out, Path(derush) if derush else None, Path(edit) if edit else None,
                                             log=log))

    def on_done(self, what: str, result) -> None:
        if what == "collect":
            self.refresh_steps()
            self.open_sheet()
        else:
            self.refresh_steps()
            self.set_status("✓ Placé : importez le .xml du dossier « export » dans Premiere", "Ok.TLabel")

    def open_sheet(self) -> None:
        out = self._out()
        if not out or not (out / "manifest.json").exists():
            return
        from .sheet import serve
        if self.server:
            self.server.shutdown()
        self.server, url = serve(out, Path(self.derush) if self.derush else None,
                                 edit=Path(self.edit) if self.edit else None)
        self.set_status("Planche ouverte dans le navigateur : gardez cette fenêtre ouverte pendant le tri.")

    def open_folder(self) -> None:
        out = self._out()
        if out and out.exists():
            os.startfile(out)


def main() -> None:
    from ..gui import main as app
    app(tab=1)


if __name__ == "__main__":
    main()
