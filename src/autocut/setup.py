"""What Autocut needs on this computer, checked and installed from the window's Installation page.

`python -m autocut.setup install <ffmpeg|model NAME|chromium|panel|update>` runs one install (the window
runs it as a job: progress, stop button).

Updates: when Autocut was installed with Autocut-Setup.exe, the page compares its version with the latest
release on GitHub; « Mettre à jour » downloads the new installer and runs it quietly (it waits for the
window to close, updates, and opens it again). A git checkout updates with git pull and Autocut.bat.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .i18n import tr

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODELS = {"large-v3": "Précise (large-v3), ~3 Go", "large-v3-turbo": "Rapide (large-v3-turbo), ~1,6 Go"}
REPO = "lihogloglo/Autocut"
EDGE = [Path(os.environ.get(v, "")) / "Microsoft/Edge/Application/msedge.exe"
        for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]


def version() -> str:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _v
    try:
        return _v("autocut")
    except PackageNotFoundError:
        return "0"


def installed_dir() -> Path | None:
    """The folder Autocut-Setup.exe installed into ({app}, holding .venv); None for a git checkout."""
    root = Path(sys.prefix).parent
    return root if (root / "unins000.exe").exists() else None


def _newer(a: str, b: str) -> bool:
    num = lambda v: tuple(int(x) for x in re.findall(r"\d+", v)[:3])      # noqa: E731
    return num(a) > num(b)


def latest_release() -> dict:
    import httpx
    r = httpx.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=6,
                  headers={"Accept": "application/vnd.github+json"}, follow_redirects=True)
    r.raise_for_status()
    d = r.json()
    asset = next((a for a in d.get("assets", []) if a.get("name") == "Autocut-Setup.exe"), None)
    return {"version": d.get("tag_name", "").lstrip("v"), "url": asset["browser_download_url"] if asset else ""}


def _update() -> dict:
    cur = version()
    row = {"id": "update", "name": tr("Autocut {version}", version=cur), "required": False, "ok": True, "action": None}
    if not installed_dir():
        return {**row, "detail": tr("Version de développement : mettez à jour avec git pull, puis Autocut.bat.")}
    try:
        latest = latest_release()
    except Exception as e:
        if getattr(getattr(e, "response", None), "status_code", 0) == 404:      # no release published yet
            return {**row, "detail": tr("À jour.")}
        return {**row, "detail": tr("Impossible de vérifier les mises à jour (pas de connexion ?).")}
    if latest["url"] and _newer(latest["version"], cur):
        return {**row, "ok": False, "detail": tr("La version {version} est disponible.", version=latest["version"]),
                "action": tr("Mettre à jour"), "note": tr("Autocut se ferme, se met à jour et se rouvre.")}
    return {**row, "detail": tr("À jour.")}


def _run_update() -> None:
    """Download the latest installer, then start it detached: it waits for the window to close."""
    import tempfile

    import httpx
    latest = latest_release()
    if not latest["url"]:
        raise SystemExit(tr("Pas d'installateur dans la dernière version."))
    dest = Path(tempfile.gettempdir()) / f"Autocut-Setup-{latest['version']}.exe"
    print(tr("[1/2] téléchargement de la version {version}", version=latest["version"]))
    with httpx.stream("GET", latest["url"], follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        tmp = dest.with_suffix(".part")
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r{done * 100 // total} %", end="")
        tmp.replace(dest)
    print()
    print(tr("[2/2] installation"))
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(dest), "/SILENT", "/relaunch=1"], creationflags=flags, close_fds=True)


def _ffmpeg() -> dict:
    found = shutil.which("ffmpeg")
    if not found:
        import static_ffmpeg
        bundled = Path(static_ffmpeg.__file__).parent / "bin" / "win32" / "ffmpeg.exe"
        found = str(bundled) if bundled.exists() else None
    return {"id": "ffmpeg", "name": "ffmpeg", "required": True, "ok": bool(found),
            "detail": tr("Trouvé : {path}", path=found) if found else
            tr("Lit et découpe l'audio des rushs. Téléchargement ~80 Mo."),
            "action": None if found else tr("Installer")}


def _gpu() -> dict:
    name = ""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=10, creationflags=NO_WINDOW)
        name = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        pass
    return {"id": "gpu", "name": tr("Carte graphique NVIDIA"), "required": False, "ok": bool(name),
            "detail": tr("{gpu} : transcription rapide (CUDA).", gpu=name) if name else
            tr("Aucune : la transcription tourne sur le processeur, plusieurs fois plus lentement."), "action": None}


def _model(name: str) -> dict:
    ok = False
    try:
        from faster_whisper.utils import download_model
        download_model(name, local_files_only=True)
        ok = True
    except Exception:  # not in the Hugging Face cache
        pass
    return {"id": f"model:{name}", "name": tr("Modèle de transcription {model}", model=tr(MODELS[name])),
            "required": name == "large-v3",
            "ok": ok, "detail": tr("Téléchargé.") if ok else tr("Sinon téléchargé au premier derush."),
            "action": None if ok else tr("Télécharger")}


def _browser() -> dict:
    edge = next((p for p in EDGE if p.exists()), None)
    pw = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    chromium = any(pw.glob("chromium*")) if pw.exists() else False
    ok = bool(edge or chromium)
    return {"id": "chromium", "name": tr("Navigateur pour les captures de pages"), "required": False, "ok": ok,
            "detail": "Microsoft Edge." if edge else "Chromium (Playwright)." if chromium else
            tr("Sans lui, pas de captures des pages citées. Téléchargement ~150 Mo."),
            "action": None if ok else tr("Installer")}


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
        return {"id": "panel", "name": tr("Panneau Premiere"), "required": False, "ok": False, "action": None,
                "detail": tr("Creative Cloud n'est pas installé sur cet ordinateur.")}
    ok = present and current
    detail = (tr("Installé. Premiere : Fenêtre › Extensions UXP › Autocut.") if ok else
              tr("Une nouvelle version est prête.") if present else
              tr("Place les illustrations directement dans la séquence ouverte, sans XML."))
    return {"id": "panel", "name": tr("Panneau Premiere"), "required": False, "ok": ok, "detail": detail,
            "action": None if ok else tr("Mettre à jour") if present else tr("Installer"),
            "note": tr("Ouvrez d'abord l'application Creative Cloud ; redémarrez Premiere ensuite.")}


def check_all() -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor
    jobs = [_update, _ffmpeg, _gpu, lambda: _model("large-v3"), lambda: _model("large-v3-turbo"), _browser, _panel]
    with ThreadPoolExecutor(len(jobs)) as ex:
        return list(ex.map(lambda f: f(), jobs))


def install(what: str, arg: str = "") -> None:
    if what == "ffmpeg":
        print(tr("[1/1] téléchargement de ffmpeg"))
        import static_ffmpeg
        static_ffmpeg.add_paths()
        print(tr("ffmpeg installé"))
    elif what == "model":
        name = arg or "large-v3"
        print(tr("[1/1] téléchargement du modèle {model}", model=name))
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from faster_whisper.utils import download_model
        print(download_model(name))
        print(tr("modèle prêt"))
    elif what == "chromium":
        print(tr("[1/1] téléchargement de Chromium"))
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    elif what == "ai":
        from .sourcing.llm import install as install_ai
        install_ai(arg)
    elif what == "update":
        _run_update()
    elif what == "panel":
        from .sourcing.bridge import install_panel
        print(tr("[1/1] installation du panneau Premiere"))
        if not install_panel(force=True):
            raise SystemExit(tr("Panneau Premiere non installé (voir ci-dessus)"))
    else:
        raise SystemExit(tr("inconnu : {what}", what=what))


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
