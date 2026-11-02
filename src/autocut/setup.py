"""What Autocut needs on this computer, checked and installed from the window's Installation page.

`python -m autocut.setup install <ffmpeg|model NAME|chromium|panel>` runs one install (the window
runs it as a job: progress, stop button).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODELS = {"large-v3": "Précise (large-v3), ~3 Go", "large-v3-turbo": "Rapide (large-v3-turbo), ~1,6 Go"}
EDGE = [Path(os.environ.get(v, "")) / "Microsoft/Edge/Application/msedge.exe"
        for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]


def _ffmpeg() -> dict:
    found = shutil.which("ffmpeg")
    if not found:
        import static_ffmpeg
        bundled = Path(static_ffmpeg.__file__).parent / "bin" / "win32" / "ffmpeg.exe"
        found = str(bundled) if bundled.exists() else None
    return {"id": "ffmpeg", "name": "ffmpeg", "required": True, "ok": bool(found),
            "detail": f"Trouvé : {found}" if found else "Lit et découpe l'audio des rushs. Téléchargement ~80 Mo.",
            "action": None if found else "Installer"}


def _gpu() -> dict:
    name = ""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=10, creationflags=NO_WINDOW)
        name = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        pass
    return {"id": "gpu", "name": "Carte graphique NVIDIA", "required": False, "ok": bool(name),
            "detail": f"{name} : transcription rapide (CUDA)." if name else
            "Aucune : la transcription tourne sur le processeur, plusieurs fois plus lentement.", "action": None}


def _model(name: str) -> dict:
    ok = False
    try:
        from faster_whisper.utils import download_model
        download_model(name, local_files_only=True)
        ok = True
    except Exception:  # not in the Hugging Face cache
        pass
    return {"id": f"model:{name}", "name": f"Modèle de transcription {MODELS[name]}", "required": name == "large-v3",
            "ok": ok, "detail": "Téléchargé." if ok else "Sinon téléchargé au premier derush.",
            "action": None if ok else "Télécharger"}


def _browser() -> dict:
    edge = next((p for p in EDGE if p.exists()), None)
    pw = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    chromium = any(pw.glob("chromium*")) if pw.exists() else False
    ok = bool(edge or chromium)
    return {"id": "chromium", "name": "Navigateur pour les captures de pages", "required": False, "ok": ok,
            "detail": "Microsoft Edge." if edge else "Chromium (Playwright)." if chromium else
            "Sans lui, pas de captures des pages citées. Téléchargement ~150 Mo.",
            "action": None if ok else "Installer"}


def panel_state() -> tuple[bool, bool, bool]:
    """(Creative Cloud installer present, panel installed, installed version is this one)."""
    from .sourcing.bridge import PANEL, UPIA
    installed = Path(os.environ.get("APPDATA", "")) / "Adobe" / "UXP" / "Plugins" / "External"
    present = any(installed.glob("com.lihogloglo.autocut_*")) if installed.exists() else False
    current = False
    stamp = Path(os.environ.get("APPDATA", Path.home())) / "autocut" / "panel.sha1"
    if present and stamp.exists():
        import hashlib
        files = sorted(f for f in PANEL.rglob("*") if f.is_file())
        digest = hashlib.sha1(b"".join(f.relative_to(PANEL).as_posix().encode() + f.read_bytes()
                                       for f in files)).hexdigest()
        current = stamp.read_text().strip() == digest
    return UPIA.exists(), present, current


def _panel() -> dict:
    cc, present, current = panel_state()
    if not cc:
        return {"id": "panel", "name": "Panneau Premiere", "required": False, "ok": False, "action": None,
                "detail": "Creative Cloud n'est pas installé sur cet ordinateur."}
    ok = present and current
    detail = ("Installé. Premiere : Fenêtre › Extensions UXP › Autocut." if ok else
              "Une nouvelle version est prête." if present else
              "Place les illustrations directement dans la séquence ouverte, sans XML.")
    return {"id": "panel", "name": "Panneau Premiere", "required": False, "ok": ok, "detail": detail,
            "action": None if ok else "Mettre à jour" if present else "Installer",
            "note": "Ouvrez d'abord l'application Creative Cloud ; redémarrez Premiere ensuite."}


def check_all() -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor
    jobs = [_ffmpeg, _gpu, lambda: _model("large-v3"), lambda: _model("large-v3-turbo"), _browser, _panel,
]
    with ThreadPoolExecutor(len(jobs)) as ex:
        return list(ex.map(lambda f: f(), jobs))


def install(what: str, arg: str = "") -> None:
    if what == "ffmpeg":
        print("[1/1] téléchargement de ffmpeg")
        import static_ffmpeg
        static_ffmpeg.add_paths()
        print("ffmpeg installé")
    elif what == "model":
        name = arg or "large-v3"
        print(f"[1/1] téléchargement du modèle {name}")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from faster_whisper.utils import download_model
        print(download_model(name))
        print("modèle prêt")
    elif what == "chromium":
        print("[1/1] téléchargement de Chromium")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    elif what == "ai":
        from .sourcing.llm import install as install_ai
        install_ai(arg)
    elif what == "panel":
        from .sourcing.bridge import install_panel
        print("[1/1] installation du panneau Premiere")
        if not install_panel(force=True):
            raise SystemExit("Panneau Premiere non installé (voir ci-dessus)")
    else:
        raise SystemExit(f"inconnu : {what}")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = sys.argv[1:]
    if args[:1] == ["install"] and len(args) >= 2:
        install(args[1], args[2] if len(args) > 2 else "")
    else:
        import json
        print(json.dumps(check_all(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
