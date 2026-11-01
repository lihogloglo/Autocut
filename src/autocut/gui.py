"""One window for the whole pipeline, one tab per step; each step also works on its own.

1. Synchro & derush: rushes (or a Premiere sequence) + optional script -> .autocut.xml
2. Illustrations: script links -> contact sheet -> files + credits + B-roll placed on the derush or the edit
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import ttk
import tkinter as tk

from . import MEDIA_EXT, SCRIPT_EXT, build_parser, run
from .premiere_xml import AUDIO_EXT
from .ui import PAD, DropZone, Fold, JobTab, make_root

SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / "autocut" / "gui.json"
MODELS = {"Précis (large-v3)": "large-v3", "Rapide (large-v3-turbo)": "large-v3-turbo"}
AUTO_SEQUENCE = "(première séquence)"


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


class _QueueWriter:
    """stdout replacement that forwards text to the Tk thread."""

    def __init__(self, tab: JobTab):
        self.tab = tab

    def write(self, text: str) -> None:
        self.tab.write(text)

    def flush(self) -> None:
        pass


def _kind(p: Path) -> str:
    if p.is_dir():
        return "Dossier"
    ext = p.suffix.lower()
    return "Séquence" if ext == ".xml" else "Son" if ext in AUDIO_EXT else "Vidéo"


class DerushTab(JobTab):
    def __init__(self, master, on_done=None, show_next=None):
        super().__init__(master)
        self.next_cb, self.show_next = on_done, show_next   # .autocut.xml + script -> illustrations tab
        self.settings = _load_settings()
        self.out_xml: Path | None = None
        script = self.settings.get("script", "")
        self.script: str = script if script and Path(script).is_file() else ""
        self.sources: list[str] = [s for s in self.settings.get("sources", []) if Path(s).exists()]

        self.zone = DropZone(
            self, "Déposez les rushs (vidéos + .wav, ou leur dossier) et le script",
            self.add, self.rows, folder=True,
            dialog_types=[("Rushs, séquence ou script",
                           " ".join(f"*{e}" for e in sorted(MEDIA_EXT | SCRIPT_EXT | {".xml"}))),
                          ("Tous", "*.*")])
        self.zone.pack(fill="x", **PAD)

        self.seq_row = ttk.Frame(self)
        ttk.Label(self.seq_row, text="Séquence à derusher").pack(side="left")
        self.sequence = tk.StringVar(value=AUTO_SEQUENCE)
        self.seq_box = ttk.Combobox(self.seq_row, textvariable=self.sequence, state="readonly", width=40)
        self.seq_box.pack(side="left", padx=8)

        opts = Fold(self, "Réglages")
        opts.pack(fill="x", **PAD)
        self.model = tk.StringVar(value=self.settings.get("model", next(iter(MODELS))))
        self.max_pause = tk.DoubleVar(value=self.settings.get("max_pause", 0.6))
        self.pad_in = tk.DoubleVar(value=self.settings.get("pad_in", 0.12))
        self.pad_out = tk.DoubleVar(value=self.settings.get("pad_out", 0.25))
        ttk.Label(opts.inner, text="Transcription").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Combobox(opts.inner, textvariable=self.model, values=list(MODELS), state="readonly", width=24) \
            .grid(row=0, column=1, columnspan=3, sticky="w", **PAD)
        for col, (label, var) in enumerate([("Pause max. (s)", self.max_pause), ("Marge début (s)", self.pad_in),
                                            ("Marge fin (s)", self.pad_out)]):
            ttk.Label(opts.inner, text=label).grid(row=1, column=col * 2, sticky="w", **PAD)
            ttk.Spinbox(opts.inner, textvariable=var, from_=0.0, to=3.0, increment=0.05, width=6) \
                .grid(row=1, column=col * 2 + 1, sticky="w", **PAD)

        bar = ttk.Frame(self)
        bar.pack(fill="x", **PAD)
        self.go = ttk.Button(bar, text="Lancer", style="Accent.TButton", width=16, command=self.start)
        self.go.pack(side="left")
        self.open_btn = ttk.Button(bar, text="Ouvrir le dossier", command=self.open_folder)
        self.next_btn = ttk.Button(bar, text="Illustrations →", command=lambda: self.show_next and self.show_next())
        self.build_footer()
        self.idle_status()
        self._list_sequences()

    # --- inputs ---------------------------------------------------------------------------
    def add(self, paths: list[Path]) -> None:
        for p in paths:
            if p.is_file() and p.suffix.lower() in SCRIPT_EXT:
                self.script = str(p)
            elif (p.is_dir() or p.suffix.lower() in MEDIA_EXT | {".xml"}) and str(p) not in self.sources:
                if p.suffix.lower() == ".xml":      # a Premiere sequence replaces the rushes, and vice versa
                    self.sources = []
                elif any(s.lower().endswith(".xml") for s in self.sources):
                    self.sources = []
                self.sources.append(str(p))
        self._list_sequences()
        self.idle_status()

    def rows(self):
        out = [("Script", self.script, lambda: self._drop_script())]
        out += [(_kind(Path(s)), s, lambda s=s: self._drop_source(s)) for s in self.sources]
        if not self.sources:
            out.append(("Rushs", "", None))
        return out

    def _drop_script(self) -> None:
        self.script = ""
        self.idle_status()

    def _drop_source(self, s: str) -> None:
        self.sources.remove(s)
        self._list_sequences()
        self.idle_status()

    def _list_sequences(self) -> None:
        names = []
        xmls = [s for s in self.sources if s.lower().endswith(".xml")]
        if xmls:
            try:
                root = ET.parse(xmls[0]).getroot()
                names = [s.findtext("name") for s in root.iter("sequence") if s.find("media") is not None]
            except (OSError, ET.ParseError):
                pass
        self.seq_box["values"] = names
        self.sequence.set(names[0] if names else AUTO_SEQUENCE)
        if len(names) > 1:
            self.seq_row.pack(fill="x", after=self.zone, **PAD)
        else:
            self.seq_row.pack_forget()

    def idle_status(self) -> None:
        if not hasattr(self, "status") or self.running:
            return
        if not self.sources:
            msg = "Ou une séquence déjà synchronisée, exportée de Premiere (Fichier > Exporter > Final Cut Pro XML)."
        elif any(s.lower().endswith(".xml") for s in self.sources):
            msg = "Derush de la séquence." if self.script else "Ajoutez le script pour le derush."
        else:
            msg = ("Synchro + derush : séquences « 1 sync », « 2 triage », « 3 derush »." if self.script
                   else "Sans script : synchro seule.")
        self.set_status(msg)

    # --- run ------------------------------------------------------------------------------
    def start(self) -> None:
        script = Path(self.script) if self.script else None
        if script and not script.is_file():
            self.set_status(f"Script introuvable : {script}", "Err.TLabel")
            return
        if not self.sources:
            self.set_status("Déposez d'abord les rushs (ou une séquence Premiere).", "Err.TLabel")
            return
        argv = [*self.sources, *([str(script)] if script else []), "--model", MODELS[self.model.get()],
                "--max-pause", str(self.max_pause.get()), "--pad-in", str(self.pad_in.get()),
                "--pad-out", str(self.pad_out.get())]
        if self.sequence.get() not in ("", AUTO_SEQUENCE):
            argv += ["--sequence", self.sequence.get()]
        args = build_parser().parse_args(argv)
        _save_settings({"script": str(script or ""), "sources": self.sources, "model": self.model.get(),
                        "max_pause": self.max_pause.get(), "pad_in": self.pad_in.get(),
                        "pad_out": self.pad_out.get()})
        self.set_status("Démarrage… (la première fois, téléchargement du modèle : ~3 Go)")
        self.run_job("derush", lambda: self._run(args))

    def _run(self, args) -> Path:
        old = sys.stdout
        sys.stdout = _QueueWriter(self)
        try:
            return run(args)
        finally:
            sys.stdout = old

    def on_busy(self, busy: bool) -> None:
        self.go["state"] = "disabled" if busy else "normal"
        if busy:
            self.open_btn.pack_forget()
            self.next_btn.pack_forget()

    def on_done(self, what: str, xml: Path) -> None:
        self.out_xml = xml
        self.set_status(f"✓ {xml.name} — à importer dans Premiere (Fichier > Importer)", "Ok.TLabel")
        self.open_btn.pack(side="left", padx=8)
        if self.script:
            self.next_btn.pack(side="left")
        if self.next_cb:
            self.next_cb(xml, Path(self.script) if self.script else None)

    def open_folder(self) -> None:
        if self.out_xml:
            os.startfile(self.out_xml.parent)


class App:
    def __init__(self, tab: int = 0):
        from .sourcing.gui import SourcesTab
        self.root = make_root()
        self.root.title("Autocut")
        self.root.geometry("780x520")
        self.root.minsize(680, 480)
        book = ttk.Notebook(self.root)
        book.pack(fill="both", expand=True, padx=6, pady=6)
        self.sources = SourcesTab(book)
        self.derush = DerushTab(book, on_done=self.sources.take_derush,
                                show_next=lambda: book.select(self.sources))
        book.add(self.derush, text="  1. Synchro & derush  ")
        book.add(self.sources, text="  2. Illustrations  ")
        book.select(tab)
        from .sourcing import bridge
        self.bridge = bridge.start(lambda: (self.sources._out(),
                                            Path(self.sources.derush) if self.sources.derush else None))

    def mainloop(self) -> None:
        self.root.mainloop()


def main(tab: int = 0) -> None:
    App(tab).mainloop()


if __name__ == "__main__":
    main()
