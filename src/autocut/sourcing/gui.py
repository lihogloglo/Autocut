"""Tk window for the B-roll sourcing: pick the script, collect, open the contact sheet, export."""

from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
import tkinter as tk

import json

from ..gui import SETTINGS as MAIN_SETTINGS
from . import collect, default_out

LLM = {"Auto (Ollama s'il tourne, sinon Claude si clé, sinon simple)": "auto",
       "Simple (noms propres, dates, mots-clés)": "off", "Ollama (local)": "ollama", "Claude (API, payant)": "claude"}


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


class SourcesApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Autocut - sources B-roll")
        self.minsize(760, 560)
        self.settings = _load_settings()
        self.q: queue.Queue = queue.Queue()
        self.server = None
        self.running = False

        pad = {"padx": 8, "pady": 4}
        files = ttk.LabelFrame(self, text="Fichiers")
        files.pack(fill="x", **pad)
        files.columnconfigure(1, weight=1)
        self.script = tk.StringVar(value=self.settings.get("script") or _main_script())
        self.derush = tk.StringVar(value=self.settings.get("derush", ""))
        ttk.Label(files, text="Script (.md avec liens)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.script).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Choisir…", command=self.pick_script).grid(row=0, column=2, **pad)
        ttk.Label(files, text="Derush (.autocut.xml)\nfacultatif : place les\nimages aux timecodes").grid(
            row=1, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.derush).grid(row=1, column=1, sticky="ew", **pad)
        dbtn = ttk.Frame(files)
        dbtn.grid(row=1, column=2, **pad)
        ttk.Button(dbtn, text="Choisir…", command=self.pick_derush).pack(side="left")
        ttk.Button(dbtn, text="Aucun", command=lambda: self.derush.set("")).pack(side="left", padx=4)

        opts = ttk.LabelFrame(self, text="Réglages")
        opts.pack(fill="x", **pad)
        self.shots = tk.BooleanVar(value=self.settings.get("shots", True))
        self.search = tk.BooleanVar(value=self.settings.get("search", True))
        self.web = tk.BooleanVar(value=self.settings.get("web", True))
        self.videos = tk.BooleanVar(value=self.settings.get("videos", True))
        self.llm = tk.StringVar(value=self.settings.get("llm", next(iter(LLM))))
        self.segment = tk.IntVar(value=self.settings.get("segment", 30))
        self.full_max = tk.IntVar(value=self.settings.get("full_max", 10))
        ttk.Checkbutton(opts, text="Captures d'écran des pages (normale + surlignée)", variable=self.shots) \
            .grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(opts, text="Recherche (Wikimedia Commons, Europeana)", variable=self.search) \
            .grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(opts, text="+ images du web (DuckDuckGo, droits inconnus)", variable=self.web) \
            .grid(row=0, column=2, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(opts, text="+ YouTube pour les notes « (extrait …) »", variable=self.videos) \
            .grid(row=1, column=2, columnspan=2, sticky="w", **pad)
        ttk.Label(opts, text="Requêtes").grid(row=2, column=0, sticky="w", **pad)
        ttk.Combobox(opts, textvariable=self.llm, values=list(LLM), state="readonly", width=48) \
            .grid(row=2, column=1, columnspan=3, sticky="w", **pad)
        ttk.Label(opts, text="Extrait vidéo (s)").grid(row=3, column=0, sticky="w", **pad)
        ttk.Spinbox(opts, textvariable=self.segment, from_=5, to=300, increment=5, width=6) \
            .grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(opts, text="Vidéo entière si moins de (min)").grid(row=3, column=2, sticky="w", **pad)
        ttk.Spinbox(opts, textvariable=self.full_max, from_=0, to=120, increment=1, width=6) \
            .grid(row=3, column=3, sticky="w", **pad)

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.go = ttk.Button(bar, text="1. Collecter", command=self.start)
        self.go.pack(side="left")
        self.sheet_btn = ttk.Button(bar, text="2. Ouvrir la planche", command=self.open_sheet)
        self.sheet_btn.pack(side="left", padx=8)
        ttk.Button(bar, text="Ouvrir le dossier", command=self.open_folder).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=200)
        self.progress.pack(side="right")

        self.log = scrolledtext.ScrolledText(self, height=16, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, **pad)
        self._write("Pour chaque lien du script : images en haute définition (Wikipédia avec auteur et licence,\n"
                    "images des articles, pages des PDF), vidéos citées avec le bon passage, captures d'écran\n"
                    "4K de la page (normale + passage surligné). Puis une recherche par paragraphe.\n\n"
                    "1. Collecter (quelques minutes ; on peut relancer, tout est mis en cache)\n"
                    "2. Ouvrir la planche : cliquez sur les vignettes à garder, puis « Exporter la sélection ».\n"
                    "   Résultat dans « <script> - sources\\export » : un dossier par section (à importer\n"
                    "   dans Premiere, un chutier par section), credits.txt pour la description YouTube,\n"
                    "   et un .xml avec la séquence B-roll (aux timecodes du derush s'il est indiqué).\n\n"
                    "Droits : vert = libre (créditer), bleu = citation (capture/extrait), orange = à vérifier,\n"
                    "rouge = agence ou banque d'images détectée.\n")
        self.after(100, self._poll)

    def _out(self) -> Path | None:
        s = self.script.get().strip()
        return default_out(Path(s)) if s else None

    def pick_script(self) -> None:
        p = Path(self.script.get()) if self.script.get() else None
        path = filedialog.askopenfilename(title="Script", initialdir=str(p.parent) if p and p.parent.exists()
                                          else str(Path.home() / "Desktop"),
                                          filetypes=[("Script Markdown", "*.md *.txt"), ("Tous", "*.*")])
        if path:
            self.script.set(path)

    def pick_derush(self) -> None:
        out = self._out()
        path = filedialog.askopenfilename(title="Séquence derush (XML de la partie 1)",
                                          initialdir=str(out.parent) if out else str(Path.home() / "Desktop"),
                                          filetypes=[("XML Premiere", "*.xml"), ("Tous", "*.*")])
        if path:
            self.derush.set(path)

    def _save(self) -> None:
        _save_settings({"script": self.script.get(), "derush": self.derush.get(),
                                   "shots": self.shots.get(), "search": self.search.get(), "web": self.web.get(),
                                   "videos": self.videos.get(), "llm": self.llm.get(),
                                   "segment": self.segment.get(), "full_max": self.full_max.get()})

    def start(self) -> None:
        script = Path(self.script.get().strip()) if self.script.get().strip() else None
        if not script or not script.is_file():
            messagebox.showerror("Autocut", "Choisissez le script (.md).")
            return
        self._save()
        self.running = True
        self.go["state"] = "disabled"
        self.progress.start(12)
        kwargs = dict(shots=self.shots.get(), search=self.search.get(), web=self.web.get(), videos=self.videos.get(),
                      llm=LLM.get(self.llm.get(), "auto"), seg_len=float(self.segment.get()),
                      full_video_max=float(self.full_max.get()) * 60, log=lambda t: self.q.put(("text", t + "\n")))
        threading.Thread(target=self._worker, args=(script, kwargs), daemon=True).start()

    def _worker(self, script: Path, kwargs: dict) -> None:
        try:
            self.q.put(("done", collect(script, **kwargs)))
        except Exception as exc:
            self.q.put(("text", traceback.format_exc()))
            self.q.put(("error", str(exc)))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "text":
                    self._write(payload)
                else:
                    self.running = False
                    self.progress.stop()
                    self.go["state"] = "normal"
                    if kind == "done":
                        self.open_sheet()
                    else:
                        messagebox.showerror("Autocut", f"Erreur :\n{payload}")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _write(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_sheet(self) -> None:
        out = self._out()
        if not out or not (out / "manifest.json").exists():
            messagebox.showinfo("Autocut", "Lancez d'abord « 1. Collecter ».")
            return
        self._save()
        from .sheet import serve
        derush = Path(self.derush.get()) if self.derush.get().strip() else None
        if self.server:
            self.server.shutdown()
        self.server, url = serve(out, derush)
        self._write(f"\nPlanche ouverte dans le navigateur : {url}\n(gardez cette fenêtre ouverte pendant le tri "
                    "et l'export)\n")

    def open_folder(self) -> None:
        out = self._out()
        if out and out.exists():
            os.startfile(out)


def main() -> None:
    SourcesApp().mainloop()


if __name__ == "__main__":
    main()
