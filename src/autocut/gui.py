"""Small Tk window around the derush: pick the script and the source, press Lancer."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
import tkinter as tk

from . import build_parser, run

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

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str) -> None:
        self.q.put(("text", text))

    def flush(self) -> None:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Autocut - derush automatique")
        self.minsize(720, 520)
        self.settings = _load_settings()
        self.q: queue.Queue = queue.Queue()
        self.out_dir: Path | None = None
        self.running = False

        pad = {"padx": 8, "pady": 4}
        files = ttk.LabelFrame(self, text="Fichiers")
        files.pack(fill="x", **pad)
        files.columnconfigure(1, weight=1)

        self.script = tk.StringVar(value=self.settings.get("script", ""))
        self.sources: list[str] = [s for s in self.settings.get("sources", []) if Path(s).exists()]
        self.sequence = tk.StringVar(value=AUTO_SEQUENCE)

        ttk.Label(files, text="Script (.md, .txt, .docx)\nfacultatif : sans script,\nsynchro seule").grid(
            row=0, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.script).grid(row=0, column=1, sticky="ew", **pad)
        sbtn = ttk.Frame(files)
        sbtn.grid(row=0, column=2, sticky="w", **pad)
        ttk.Button(sbtn, text="Choisir…", command=self.pick_script).pack(side="left")
        ttk.Button(sbtn, text="Aucun", command=lambda: self.script.set("")).pack(side="left", padx=4)

        ttk.Label(files, text="Rushs (vidéos + .wav,\nou un dossier)\nou séquence Premiere (.xml)").grid(
            row=1, column=0, sticky="nw", **pad)
        self.src_list = tk.Listbox(files, height=5, selectmode="extended")
        self.src_list.grid(row=1, column=1, sticky="ew", **pad)
        btns = ttk.Frame(files)
        btns.grid(row=1, column=2, sticky="nw", **pad)
        ttk.Button(btns, text="Fichiers…", command=self.pick_files).pack(fill="x")
        ttk.Button(btns, text="Dossier…", command=self.pick_folder).pack(fill="x", pady=2)
        ttk.Button(btns, text="Retirer", command=self.remove_sources).pack(fill="x")
        self._refresh_sources()

        ttk.Label(files, text="Séquence (XML)").grid(row=2, column=0, sticky="w", **pad)
        self.seq_box = ttk.Combobox(files, textvariable=self.sequence, state="readonly", values=[AUTO_SEQUENCE])
        self.seq_box.grid(row=2, column=1, sticky="w", **pad)

        opts = ttk.LabelFrame(self, text="Réglages")
        opts.pack(fill="x", **pad)
        self.model = tk.StringVar(value=self.settings.get("model", next(iter(MODELS))))
        self.max_pause = tk.DoubleVar(value=self.settings.get("max_pause", 0.6))
        self.pad_in = tk.DoubleVar(value=self.settings.get("pad_in", 0.12))
        self.pad_out = tk.DoubleVar(value=self.settings.get("pad_out", 0.25))
        ttk.Label(opts, text="Transcription").grid(row=0, column=0, sticky="w", **pad)
        ttk.Combobox(opts, textvariable=self.model, values=list(MODELS), state="readonly", width=24) \
            .grid(row=0, column=1, sticky="w", **pad)
        for col, (label, var) in enumerate([("Pause max. (s)", self.max_pause), ("Marge début (s)", self.pad_in),
                                            ("Marge fin (s)", self.pad_out)]):
            ttk.Label(opts, text=label).grid(row=1, column=col * 2, sticky="w", **pad)
            ttk.Spinbox(opts, textvariable=var, from_=0.0, to=3.0, increment=0.05, width=6) \
                .grid(row=1, column=col * 2 + 1, sticky="w", **pad)

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.go = ttk.Button(bar, text="Lancer", command=self.start)
        self.go.pack(side="left")
        self.open_btn = ttk.Button(bar, text="Ouvrir le dossier", command=self.open_folder, state="disabled")
        self.open_btn.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=200)
        self.progress.pack(side="right")

        self.log = scrolledtext.ScrolledText(self, height=16, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, **pad)
        self._write("Ajoutez les rushs (vidéos de la caméra + .wav de l'enregistreur, ou leur dossier) :\n"
                    "ils sont synchronisés par le son. Ou bien une séquence déjà synchronisée, exportée\n"
                    "depuis Premiere (Fichier > Exporter > Final Cut Pro XML). Puis le script, et lancez.\n\n"
                    "Résultat : un seul .autocut.xml à importer dans Premiere, avec 3 séquences :\n"
                    "  1 sync    les rushs synchronisés\n"
                    "  2 triage  tout est gardé, découpé et coloré par prise\n"
                    "            (ratées en Rose, bavardages en Marron, silences en Bleu)\n"
                    "  3 derush  seulement les bonnes prises, silences supprimés\n"
                    "et .autocut.txt, le rapport phrase par phrase. Sans script : seulement 1 sync.\n\n"
                    "La première utilisation télécharge le modèle de transcription (~3 Go).\n")
        self._list_sequences()
        self.after(100, self._poll)

    # --- file pickers -----------------------------------------------------------------
    def _initial_dir(self, var: tk.StringVar) -> str:
        p = Path(var.get()) if var.get() else None
        return str(p.parent) if p and p.parent.exists() else str(Path.home() / "Desktop")

    def pick_script(self) -> None:
        path = filedialog.askopenfilename(title="Script", initialdir=self._initial_dir(self.script),
                                          filetypes=[("Script", "*.md *.txt *.docx"), ("Tous", "*.*")])
        if path:
            self.script.set(path)

    def _refresh_sources(self) -> None:
        self.src_list.delete(0, "end")
        for src in self.sources:
            self.src_list.insert("end", src)
        if hasattr(self, "seq_box"):
            self._list_sequences()

    def _add_sources(self, paths) -> None:
        for p in paths:
            if p and p not in self.sources:
                self.sources.append(p)
        self._refresh_sources()

    def _source_dir(self) -> str:
        p = Path(self.sources[-1]) if self.sources else None
        if p and p.is_dir():
            return str(p)
        return str(p.parent) if p and p.parent.exists() else str(Path.home() / "Desktop")

    def pick_files(self) -> None:
        self._add_sources(filedialog.askopenfilenames(
            title="Rushs ou séquence Premiere", initialdir=self._source_dir(),
            filetypes=[("Rushs", "*.mp4 *.mov *.mxf *.mkv *.mts *.wav *.bwf *.aif *.aiff *.flac *.mp3 *.m4a"),
                       ("Séquence Premiere (XML)", "*.xml"), ("Tous", "*.*")]))

    def pick_folder(self) -> None:
        self._add_sources([filedialog.askdirectory(title="Dossier des rushs", initialdir=self._source_dir())])

    def remove_sources(self) -> None:
        picked = set(self.src_list.curselection())
        self.sources = [s for k, s in enumerate(self.sources) if k not in picked] if picked else []
        self._refresh_sources()

    def _list_sequences(self) -> None:
        names = [AUTO_SEQUENCE]
        xmls = [s for s in self.sources if s.lower().endswith(".xml")]
        if xmls:
            try:
                root = ET.parse(xmls[0]).getroot()
                names += [s.findtext("name") for s in root.iter("sequence") if s.find("media") is not None]
            except (OSError, ET.ParseError):
                pass
        self.seq_box["values"] = names
        self.seq_box["state"] = "readonly" if xmls else "disabled"
        self.sequence.set(names[1] if len(names) == 2 else AUTO_SEQUENCE)

    # --- run ----------------------------------------------------------------------------
    def start(self) -> None:
        script = Path(self.script.get()) if self.script.get().strip() else None
        if script and not script.is_file():
            messagebox.showerror("Autocut", f"Script introuvable :\n{script}")
            return
        if not self.sources:
            messagebox.showerror("Autocut", "Ajoutez les rushs (ou une séquence Premiere).")
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

        self.running = True
        self.go["state"] = "disabled"
        self.open_btn["state"] = "disabled"
        self.progress.start(12)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()

    def _worker(self, args) -> None:
        old = sys.stdout
        sys.stdout = _QueueWriter(self.q)
        try:
            self.q.put(("done", run(args)))
        except Exception as exc:  # shown to the user, details in the log
            traceback.print_exc(file=sys.stdout)
            self.q.put(("error", str(exc)))
        finally:
            sys.stdout = old

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "text":
                    self._write(payload)
                else:
                    self._finish(kind, payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _write(self, text: str) -> None:
        self.log.configure(state="normal")
        for i, part in enumerate(text.split("\r")):
            if i > 0:  # carriage return: overwrite the current line (progress updates)
                self.log.delete("end-1c linestart", "end-1c")
            self.log.insert("end", part)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _finish(self, kind: str, payload) -> None:
        self.running = False
        self.progress.stop()
        self.go["state"] = "normal"
        if kind == "done":
            self.out_dir = payload
            self.open_btn["state"] = "normal"
            messagebox.showinfo("Autocut", "Terminé.\nImportez le .autocut.xml dans Premiere "
                                           "(Fichier > Importer).")
        else:
            messagebox.showerror("Autocut", f"Erreur :\n{payload}")

    def open_folder(self) -> None:
        if self.out_dir:
            os.startfile(self.out_dir)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
