"""Interface language. The French text is the key: locales/<lang>/*.json map it to the translation.

Adding a language = adding a folder locales/<code>/ with the same JSON files (missing strings stay in
French) and its name in NAMES. The window, the planche, the storyboard page and the Premiere panel all
read the same catalogue; Python messages go through tr(). Placeholders are {name}, filled by tr()/t().
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

LOCALES = Path(__file__).with_name("locales")
NAMES = {"fr": "Français", "en": "English"}       # interface languages offered in the window
STATE_FILE = Path(os.environ.get("APPDATA", Path.home())) / "fauxraccord" / "app.json"


def _system_lang() -> str:
    try:
        import ctypes
        import locale
        code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    except Exception:
        import locale
        code = (locale.getlocale()[0] or "")
    code = code.split("_")[0].lower()
    return code if code in NAMES else "en"


def ui_lang() -> str:
    """FAUXRACCORD_LANG (set for the jobs the window starts), else the window's choice, else Windows'."""
    env = os.environ.get("FAUXRACCORD_LANG", "")
    if env in NAMES:
        return env
    try:
        lang = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("ui_lang", "")
        if lang in NAMES:
            return lang
    except (OSError, ValueError):
        pass
    return _system_lang()


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, str]:
    out: dict[str, str] = {}
    folder = LOCALES / lang
    if lang != "fr" and folder.is_dir():
        for f in sorted(folder.glob("*.json")):
            out.update(json.loads(f.read_text(encoding="utf-8")))
    return out


def tr(text: str, lang: str | None = None, **values) -> str:
    """The translation of a French interface string, with {placeholders} filled."""
    s = catalog(lang or ui_lang()).get(text) or text
    return s.format(**values) if values else s


def language_name(code: str) -> str:
    """A language's name in French, for the (French) AI prompts."""
    return {"fr": "français", "en": "anglais"}.get(code, NAMES.get(code, code))


def localize_prompt(prompt: str) -> str:
    """AI prompts say what to write « en français »: the notes and shots follow the interface language."""
    lang = ui_lang()
    return prompt if lang == "fr" else prompt.replace("en français", f"en {language_name(lang)}")


def js(lang: str | None = None) -> str:
    """i18n.js with the catalogue inlined, for pages served over HTTP (planche, storyboard)."""
    lang = lang or ui_lang()
    lib = (Path(__file__).parent / "web" / "i18n.js").read_text(encoding="utf-8")
    return f"window.I18N_INIT = {json.dumps({'lang': lang, 'dict': catalog(lang)}, ensure_ascii=False)};\n{lib}"
