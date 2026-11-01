"""Shared pieces of the Autocut window: theme, file drop zone, folding sections, status line + hidden log."""

from __future__ import annotations

import queue
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # no drag and drop: clicking the zone still opens a file dialog
    TkinterDnD = None

PAD = {"padx": 10, "pady": 5}


def _windows_dark() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def make_root() -> tk.Tk:
    """Tk root with drag and drop when tkdnd loads, and the Windows 11 look (light/dark like Windows)."""
    root = None
    if TkinterDnD:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            root = None
    root = root or tk.Tk()
    try:
        import sv_ttk
        sv_ttk.set_theme("dark" if _windows_dark() else "light")
    except Exception:
        pass
    style = ttk.Style(root)
    style.configure("Dim.TLabel", foreground="#8a8a8a")
    style.configure("Big.TLabel", font=("Segoe UI", 11))
    style.configure("Ok.TLabel", foreground="#3fb950")
    style.configure("Err.TLabel", foreground="#f85149")
    return root


def short(path: str | Path, n: int = 60) -> str:
    s = str(path)
    return s if len(s) <= n else "…" + s[-(n - 1):]


class DropZone(ttk.Frame):
    """A card that takes dropped files (or opens a dialog when clicked) and lists what it holds.

    `rows()` returns [(kind, path, remove_callback)], refreshed by `refresh()`."""

    def __init__(self, master, hint: str, on_paths, rows, dialog_types, folder: bool = False):
        super().__init__(master, style="Card.TFrame", padding=14)
        self.on_paths, self.rows, self.types = on_paths, rows, dialog_types
        self.head = ttk.Frame(self)
        self.head.pack(fill="x")
        self.hint = ttk.Label(self.head, text=hint, style="Big.TLabel", cursor="hand2")
        self.hint.pack(side="left")
        links = ttk.Frame(self.head)
        links.pack(side="right")
        ttk.Button(links, text="Fichiers…", command=self.pick_files).pack(side="left")
        if folder:
            ttk.Button(links, text="Dossier…", command=self.pick_folder).pack(side="left", padx=(6, 0))
        self.body = ttk.Frame(self)
        self.body.pack(fill="x", pady=(8, 0))
        self.hint.bind("<Button-1>", lambda e: self.pick_files())
        for w in (master, self, self.head, self.hint, self.body):   # the whole tab takes drops
            self._register(w)
        self.refresh()

    def _register(self, w) -> None:
        if not hasattr(w, "drop_target_register"):
            return
        try:
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", self._drop)
            w.dnd_bind("<<DropEnter>>", lambda e: self._glow(True))
            w.dnd_bind("<<DropLeave>>", lambda e: self._glow(False))
        except Exception:
            pass

    def _glow(self, on: bool):
        self.hint.configure(style="Ok.TLabel" if on else "Big.TLabel")
        return "copy"

    def _drop(self, event):
        self._glow(False)
        self.on_paths([Path(p) for p in self.tk.splitlist(event.data)])
        self.refresh()
        return "copy"

    def pick_files(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=self.types)
        if paths:
            self.on_paths([Path(p) for p in paths])
            self.refresh()

    def pick_folder(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.on_paths([Path(path)])
            self.refresh()

    def refresh(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        rows = self.rows()
        self.body.columnconfigure(1, weight=1)
        for r, (kind, path, remove) in enumerate(rows):
            ttk.Label(self.body, text=kind, style="Dim.TLabel", width=10).grid(row=r, column=0, sticky="w")
            if path:
                name = ttk.Label(self.body, text=Path(path).name)
                name.grid(row=r, column=1, sticky="w")
                Tooltip(name, str(path))
                ttk.Button(self.body, text="✕", width=3, style="Toolbutton", command=lambda f=remove: (
                    f(), self.refresh())).grid(row=r, column=2, sticky="e")
            else:
                ttk.Label(self.body, text="—", style="Dim.TLabel").grid(row=r, column=1, sticky="w")
            for w in self.body.grid_slaves(row=r):
                self._register(w)
        self.body.pack_configure(pady=(8, 0) if rows else 0)


class Tooltip:
    def __init__(self, widget, text: str):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _=None):
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty() + 22}")
        ttk.Label(self.tip, text=self.text, padding=4, relief="solid", borderwidth=1).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Fold(ttk.Frame):
    """A titled section that starts folded."""

    def __init__(self, master, title: str, opened: bool = False):
        super().__init__(master)
        self.title, self.opened = title, opened
        self.toggle_btn = ttk.Button(self, style="Toolbutton", command=self.toggle)
        self.toggle_btn.pack(anchor="w")
        self.inner = ttk.Frame(self)
        self._show()

    def toggle(self) -> None:
        self.opened = not self.opened
        self._show()

    def open(self) -> None:
        if not self.opened:
            self.toggle()

    def _show(self) -> None:
        self.toggle_btn.configure(text=("▾ " if self.opened else "▸ ") + self.title)
        if self.opened:
            self.inner.pack(fill="both", expand=True, pady=(4, 0))
        else:
            self.inner.pack_forget()


class JobTab(ttk.Frame):
    """A tab that runs long jobs in a thread: status line (last log line), progress bar, folded log."""

    def __init__(self, master):
        super().__init__(master, padding=6)
        self.q: queue.Queue = queue.Queue()
        self.running = False
        self._line = ""

    def build_footer(self) -> None:
        self.status = ttk.Label(self, text="", style="Dim.TLabel", anchor="w")
        self.status.pack(fill="x", **PAD)
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.details = Fold(self, "Détails")
        self.details.pack(fill="both", expand=True, **PAD)
        self.log = scrolledtext.ScrolledText(self.details.inner, height=12, font=("Consolas", 9), state="disabled",
                                             relief="flat", borderwidth=0)
        self.log.pack(fill="both", expand=True)
        self.after(100, self._poll)

    def set_status(self, text: str, style: str = "Dim.TLabel") -> None:
        self.status.configure(text=text, style=style)

    def run_job(self, what: str, job) -> None:
        """Run job() in a thread; on_done(what, result) or on_error(message) is called in the Tk thread."""
        self.running = True
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.pack(fill="x", before=self.details, **PAD)
        self.progress.start(12)
        self.on_busy(True)

        def work():
            try:
                self.q.put((what, job()))
            except Exception as exc:  # shown to the user, details in the log
                self.q.put(("text", traceback.format_exc()))
                self.q.put(("error", str(exc)))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def write(self, text: str) -> None:
        self.q.put(("text", text))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "text":
                    self._append(payload)
                    continue
                self.running = False
                self.progress.stop()
                self.progress.pack_forget()
                self.on_busy(False)
                if kind == "error":
                    self.set_status(f"Erreur : {payload}", "Err.TLabel")
                    self.details.open()
                else:
                    self.on_done(kind, payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        for i, part in enumerate(text.split("\r")):
            if i > 0:  # carriage return: overwrite the current line (progress updates)
                self.log.delete("end-1c linestart", "end-1c")
            self.log.insert("end", part)
        self.log.see("end")
        self.log.configure(state="disabled")
        last = self.log.get("end-1c linestart", "end-1c").strip() or self.log.get("end-2l linestart", "end-2l lineend")
        if self.running and last.strip():
            self.set_status(last.strip()[:110])

    # overridden by the tabs
    def on_busy(self, busy: bool) -> None: ...
    def on_done(self, what: str, result) -> None: ...
