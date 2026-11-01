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
        self.source = tk.StringVar(value=self.settings.get("source", ""))
        self.sequence = tk.StringVar(value=AUTO_SEQUENCE)

        ttk.Label(files, text="Script (.md, .txt, .docx)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.script).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Choisir…", command=self.pick_script).grid(row=0, column=2, **pad)

        ttk.Label(files, text="Séquence Premiere (.xml)\nou vidéo").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.source).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Choisir…", command=self.pick_source).grid(row=1, column=2, **pad)

        ttk.Label(files, text="Séquence").grid(row=2, column=0, sticky="w", **pad)
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
        self.go = ttk.Button(bar, text="Lancer le derush", command=self.start)
        self.go.pack(side="left")
        self.open_btn = ttk.Button(bar, text="Ouvrir le dossier", command=self.open_folder, state="disabled")
        self.open_btn.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=200)
        self.progress.pack(side="right")

        self.log = scrolledtext.ScrolledText(self, height=16, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, **pad)
        self._write("Choisissez le script et la séquence exportée depuis Premiere\n"
                    "(Fichier > Exporter > Final Cut Pro XML), puis lancez.\n\n"
                    "Résultat, à côté du fichier source :\n"
                    "  .derush.xml  le derush : silences et prises ratées supprimés, prises colorées\n"
                    "  .backup.xml  sauvegarde : silences supprimés, toutes les prises gardées\n"
                    "               (ratées en Rose, bavardages en Marron)\n"
                    "  .derush.txt  rapport phrase par phrase\n\n"
                    "La première utilisation télécharge le modèle de transcription (~3 Go).\n")
        if self.source.get().lower().endswith(".xml"):
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

    def pick_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Séquence Premiere ou vidéo", initialdir=self._initial_dir(self.source),
            filetypes=[("Séquence Premiere (XML)", "*.xml"), ("Vidéo / audio", "*.mp4 *.mov *.mxf *.wav *.mkv"),
                       ("Tous", "*.*")])
        if path:
            self.source.set(path)
            self._list_sequences()

    def _list_sequences(self) -> None:
        names = [AUTO_SEQUENCE]
        try:
            root = ET.parse(self.source.get()).getroot()
            names += [s.findtext("name") for s in root.iter("sequence") if s.find("media") is not None]
        except (OSError, ET.ParseError):
            pass
        self.seq_box["values"] = names
        self.sequence.set(names[1] if len(names) == 2 else AUTO_SEQUENCE)

    # --- run ----------------------------------------------------------------------------
    def start(self) -> None:
        script, source = Path(self.script.get()), Path(self.source.get())
        if not script.is_file() or not source.is_file():
            messagebox.showerror("Autocut", "Choisissez un script et une séquence (ou vidéo) existants.")
            return
        argv = [str(source), str(script), "--model", MODELS[self.model.get()],
                "--max-pause", str(self.max_pause.get()), "--pad-in", str(self.pad_in.get()),
                "--pad-out", str(self.pad_out.get())]
        if self.sequence.get() not in ("", AUTO_SEQUENCE):
            argv += ["--sequence", self.sequence.get()]
        args = build_parser().parse_args(argv)
        _save_settings({"script": str(script), "source": str(source), "model": self.model.get(),
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
            messagebox.showinfo("Autocut", "Derush terminé.\nImportez le .derush.xml dans Premiere "
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
