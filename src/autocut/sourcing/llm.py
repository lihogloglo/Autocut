"""The AI engines Autocut can ask, for every step that needs one (illustration search, picture check,
storyboard). One call shape for all: a system prompt, a user message (text and JPEG images), a JSON
schema; back comes the parsed JSON.

Engines:
  gemini       Gemini API, key typed in the window (cheap, the default when a key is saved)
  claude       Claude API (ANTHROPIC_API_KEY or an `ant auth login` profile)
  claude-code  Claude subscription (Pro/Max), through the user's own Claude Code CLI
  codex        ChatGPT subscription, through the user's own Codex CLI
  antigravity  Gemini subscription (Google AI Pro/Ultra), through the user's own Antigravity CLI
  ollama       local model, text only (no picture check)

Subscriptions are used only by running the unmodified official CLIs, signed in by the user: their
login tokens are never read or copied here."""

from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

APPDATA = Path(os.environ.get("APPDATA", Path.home())) / "autocut"
KEYS_FILE = APPDATA / "keys.json"     # kept apart from app.json, which the page receives whole

CLAUDE_MODEL = os.environ.get("AUTOCUT_CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_FAST = os.environ.get("AUTOCUT_CLAUDE_FAST_MODEL", "claude-sonnet-5-5")
GEMINI_MODEL = os.environ.get("AUTOCUT_GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FAST = os.environ.get("AUTOCUT_GEMINI_FAST_MODEL", "gemini-3.5-flash-lite")
# Images sent to Gemini: 448 px thumbnails need no more than "medium" (533 tokens each instead of 1081).
GEMINI_MEDIA = {"low": "MEDIA_RESOLUTION_LOW", "medium": "MEDIA_RESOLUTION_MEDIUM", "high": "MEDIA_RESOLUTION_HIGH"}.get(
    os.environ.get("AUTOCUT_GEMINI_MEDIA", "medium"), "MEDIA_RESOLUTION_MEDIUM")
# $ per million tokens (input, output incl. thinking), paid tier: ai.google.dev/gemini-api/docs/pricing
GEMINI_PRICES = {"gemini-3.8-flash": [("2027-01-01", 1.50, 7.50), ("", 0.75, 3.75)],
                 "gemini-3.5-flash-lite": [("", 0.30, 2.50)]}
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ENGINES = {
    "gemini": {"label": "Gemini", "how": "clé API", "vision": True},
    "claude-code": {"label": "Claude", "how": "abonnement Pro / Max", "vision": True, "exe": "claude"},
    "codex": {"label": "ChatGPT", "how": "abonnement, via Codex", "vision": True, "exe": "codex"},
    "antigravity": {"label": "Gemini", "how": "abonnement Google AI, via Antigravity", "vision": True, "exe": "agy"},
    "claude": {"label": "Claude", "how": "clé API", "vision": True},
    "ollama": {"label": "Ollama", "how": "local", "vision": False},
}
AUTO_ORDER = ["gemini", "claude", "claude-code", "codex", "antigravity", "ollama"]

_quality = os.environ.get("AUTOCUT_QUALITY", "best")


def set_quality(q: str) -> None:
    global _quality
    _quality = "fast" if q == "fast" else "best"


def label(engine: str) -> str:
    e = ENGINES.get(engine)
    return f"{e['label']} ({e['how']})" if e else engine


# --- Keys and flags ---------------------------------------------------------------------------------

def _keys() -> dict:
    try:
        return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_key(name: str, value) -> None:
    keys = _keys()
    if value:
        keys[name] = value
    else:
        keys.pop(name, None)
    APPDATA.mkdir(parents=True, exist_ok=True)
    tmp = KEYS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(keys, indent=1), encoding="utf-8")
    tmp.replace(KEYS_FILE)


def gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or _keys().get("gemini") or "").strip()


def claude_available() -> bool:
    """An API key, a token, or an `ant auth login` profile (the SDK reads all three)."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return any((d / "anthropic").is_dir() for d in (Path.home() / ".config", Path(os.environ.get("APPDATA", "~"))))


def ollama_available() -> str | None:
    import httpx
    try:
        tags = httpx.get("http://localhost:11434/api/tags", timeout=2).json().get("models", [])
    except Exception:
        return None
    wanted = os.environ.get("AUTOCUT_OLLAMA_MODEL")
    names = [m["name"] for m in tags if "embed" not in m["name"]]
    if wanted and wanted in names:
        return wanted
    return names[0] if names else None


# --- The CLIs ---------------------------------------------------------------------------------------

_KNOWN = {
    "claude": [Path.home() / ".local/bin/claude.exe"],
    "codex": [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/OpenAI/Codex/bin/codex.exe"],
    "agy": [Path(os.environ.get("LOCALAPPDATA", "")) / "agy/bin/agy.exe", Path.home() / ".local/bin/agy.exe"],
}


def exe(name: str) -> str | None:
    """The CLI's real .exe when there is one (a .cmd shim would mangle quoted arguments)."""
    for p in _KNOWN.get(name, []):
        if p.is_file():
            return str(p)
    found = shutil.which(name)
    if found and found.lower().endswith(".cmd"):
        alt = shutil.which(name + ".exe")
        return alt or found
    return found


def _run(cmd: list[str], stdin: str = "", cwd: str | None = None, timeout: float = 900,
         drop_env: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in drop_env and not k.startswith("CLAUDECODE")}
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=cwd, timeout=timeout, env=env, creationflags=NO_WINDOW)


def _cli_connected(engine: str) -> tuple[bool, str]:
    path = exe(ENGINES[engine]["exe"])
    if not path:
        return False, "non installé"
    try:
        if engine == "claude-code":
            r = _run([path, "auth", "status"], timeout=20, drop_env=("ANTHROPIC_API_KEY",))
            if r.returncode != 0:
                return False, "pas connecté"
            try:
                method = json.loads(r.stdout).get("authMethod", "")
            except ValueError:
                method = ""
            return True, {"claude.ai": "connecté avec l'abonnement"}.get(method, f"connecté ({method or 'ok'})")
        if engine == "codex":
            r = _run([path, "login", "status"], timeout=20)
            text = (r.stdout + r.stderr).strip()
            ok = r.returncode == 0 and "logged in" in text.lower()
            return ok, ("connecté avec ChatGPT" if "chatgpt" in text.lower() else text[:80]) if ok else "pas connecté"
        if engine == "antigravity":
            models = _agy_models(path, refresh=True)     # `agy models` needs a signed-in session
            return (True, "connecté au compte Google") if models else (False, "pas connecté")
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{type(e).__name__}"
    return False, ""


def status(engine: str) -> dict:
    """{id, label, how, installed, connected, detail} for the AI page."""
    e = ENGINES[engine]
    out = {"id": engine, "label": e["label"], "how": e["how"], "vision": e["vision"], "cli": "exe" in e}
    if engine == "gemini":
        k = gemini_key()
        out.update(installed=True, connected=bool(k),
                   detail=f"clé enregistrée ({k[:4]}…{k[-4:]}), {GEMINI_MODEL}" if len(k) > 12 else "pas de clé")
    elif engine == "claude":
        ok = claude_available()
        out.update(installed=True, connected=ok, detail=f"identifiants trouvés, {CLAUDE_MODEL}" if ok else
                   "variable ANTHROPIC_API_KEY absente")
    elif engine == "ollama":
        m = ollama_available()
        out.update(installed=bool(m), connected=bool(m), detail=f"en marche : {m}" if m else "pas lancé")
    else:
        installed = bool(exe(e["exe"]))
        ok, detail = _cli_connected(engine) if installed else (False, "non installé")
        out.update(installed=installed, connected=ok, detail=detail)
    return out


def available(engine: str) -> bool:
    if engine == "gemini":
        return bool(gemini_key())
    if engine == "claude":
        return claude_available()
    if engine == "ollama":
        return bool(ollama_available())
    if engine in ENGINES:
        return _cli_connected(engine)[0]
    return False


def candidates(pref: str) -> list[str]:
    """Engines to try, in order: the chosen one, or (auto) every connected one."""
    if pref in ("off", "", None):
        return []
    if pref in ENGINES:
        return [pref]
    return [e for e in AUTO_ORDER if available(e)]


def connect(engine: str) -> str:
    """Opens the CLI's own sign-in (browser) in a console window. Returns what the user should expect."""
    path = exe(ENGINES[engine]["exe"])
    if not path:
        raise RuntimeError("pas installé")
    cmd = {"claude-code": [path, "auth", "login"], "codex": [path, "login"], "antigravity": [path]}[engine]
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY" and not k.startswith("CLAUDECODE")}
    subprocess.Popen(cmd, env=env, cwd=str(Path.home()), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    if engine == "antigravity":
        return "Connectez-vous dans la fenêtre qui s'ouvre (compte Google, dans le navigateur), puis fermez-la."
    return "Connectez-vous dans le navigateur qui s'ouvre, puis revenez ici."


def test(engine: str) -> str:
    """A tiny request with an image: proves the engine answers in JSON and can see. Returns its answer."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 160), (200, 30, 30))
    ImageDraw.Draw(im).rectangle((110, 40, 210, 120), fill=(255, 255, 255))
    schema = {"type": "object", "additionalProperties": False, "required": ["color"],
              "properties": {"color": {"type": "string"}}}
    content = ["Quelle est la couleur du fond de cette image ? Un mot, en français.", jpeg(im, 320)]
    if not ENGINES[engine]["vision"]:
        content = ["Réponds « ok » dans le champ color."]
    answer = ask(engine, "Tu réponds en JSON.", content, schema, effort="low", timeout=300)
    return str(answer.get("color", ""))[:40]


# --- Images -------------------------------------------------------------------------------------

def jpeg(im, side: int = 512) -> bytes:
    """A PIL image as a small JPEG, enough for a model to tell what it shows."""
    im = im.copy()
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=82)
    return buf.getvalue()


# --- Calls --------------------------------------------------------------------------------------
# `content` is a list of str and bytes (JPEG images), in order.

# --- Usage: what the calls of this run consumed -----------------------------------------------------

_usage: dict = {}
_usage_lock = threading.Lock()


def _count(engine: str, model: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
    with _usage_lock:
        u = _usage.setdefault((engine, model), {"calls": 0, "in": 0, "out": 0})
        u["calls"] += 1
        u["in"] += int(tokens_in or 0)
        u["out"] += int(tokens_out or 0)


def _gemini_price(model: str) -> tuple[float, float] | None:
    today = time.strftime("%Y-%m-%d")
    for since, p_in, p_out in GEMINI_PRICES.get(model, []):
        if today >= since:
            return p_in, p_out
    return None


def usage_summary() -> str:
    """One line per engine used: calls, tokens and, for the Gemini API, the cost on a paid key."""
    lines = []
    with _usage_lock:
        items = sorted(_usage.items())
    for (engine, model), u in items:
        k = lambda n: f"{n / 1e6:.2f} M" if n >= 1e6 else f"{n / 1e3:.0f} k"   # noqa: E731
        tokens = f"{u['calls']} appels, {k(u['in'])} jetons en entrée, {k(u['out'])} en sortie"
        if engine == "gemini" and (price := _gemini_price(model)):
            cost = u["in"] / 1e6 * price[0] + u["out"] / 1e6 * price[1]
            lines.append(f"{label(engine)} {model} : {tokens} ≈ {cost:.3f} $ (clé payante ; 0 $ en gratuit)")
        elif "exe" in ENGINES.get(engine, {}):
            lines.append(f"{label(engine)} : {tokens} (compris dans l'abonnement)")
        else:
            lines.append(f"{label(engine)} {model} : {tokens}")
    return "\n".join(lines)


_gates = {"gemini": threading.Semaphore(int(os.environ.get("AUTOCUT_GEMINI_PARALLEL", "4"))),
          "claude": threading.Semaphore(4), "cli": threading.Semaphore(int(os.environ.get("AUTOCUT_CLI_PARALLEL", "2")))}


def _strip_schema(s, drop=("additionalProperties",)):
    if isinstance(s, dict):
        return {k: _strip_schema(v, drop) for k, v in s.items() if k not in drop}
    if isinstance(s, list):
        return [_strip_schema(x, drop) for x in s]
    return s


def _gemini_error(r) -> str:
    try:
        return r.json()["error"]["message"][:200]
    except Exception:
        return r.text[:200]


def check_gemini(key: str) -> str | None:
    """None when the key works with the chosen model, else what went wrong (in French, for the window)."""
    import httpx
    try:
        r = httpx.get(f"{GEMINI_API}/models/{GEMINI_MODEL}", headers={"x-goog-api-key": key}, timeout=15)
    except httpx.HTTPError as e:
        return f"Google injoignable ({type(e).__name__})"
    if r.status_code == 200:
        return None
    msg = _gemini_error(r)
    if r.status_code in (400, 401, 403):
        return f"clé refusée : {msg}"
    if r.status_code == 404:
        return f"clé valide, mais le modèle {GEMINI_MODEL} est introuvable (AUTOCUT_GEMINI_MODEL pour en choisir un autre)"
    return f"erreur {r.status_code} : {msg}"


def gemini_json(system: str, content: list, schema: dict, *, timeout: float = 600) -> dict:
    import httpx
    key = gemini_key()
    if not key:
        raise RuntimeError("pas de clé Gemini")
    parts = [{"text": c} if isinstance(c, str) else
             {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(c).decode()}} for c in content]
    model = GEMINI_FAST if _quality == "fast" else GEMINI_MODEL
    url = f"{GEMINI_API}/models/{model}:generateContent"
    # JSON Schema first; then the older schema field; then plain JSON with the schema in the prompt.
    configs = [{"response_mime_type": "application/json", "response_json_schema": schema},
               {"response_mime_type": "application/json", "response_schema": _strip_schema(schema)},
               {"response_mime_type": "application/json"}]
    if any(not isinstance(c, str) for c in content):
        for cfg in configs:
            cfg["media_resolution"] = GEMINI_MEDIA
    last = ""
    for i, cfg in enumerate(configs):
        sys_text = system if i < 2 else system + "\n\nRéponds en JSON selon ce schéma :\n" + json.dumps(schema)
        body = {"system_instruction": {"parts": [{"text": sys_text}]},
                "contents": [{"role": "user", "parts": parts}], "generation_config": cfg}
        for attempt in range(6):
            with _gates["gemini"]:
                r = httpx.post(url, headers={"x-goog-api-key": key}, json=body, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 2 ** attempt * 2) + random.random())
                continue
            break
        if r.status_code == 400:
            last = _gemini_error(r)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Gemini {r.status_code} : {_gemini_error(r)}")
        data = r.json()
        meta = data.get("usageMetadata") or {}
        _count("gemini", model, meta.get("promptTokenCount"),
               (meta.get("candidatesTokenCount") or 0) + (meta.get("thoughtsTokenCount") or 0))
        cand = (data.get("candidates") or [{}])[0]
        if cand.get("finishReason") == "MAX_TOKENS":
            raise RuntimeError("réponse tronquée")
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
        if not text:
            block = (data.get("promptFeedback") or {}).get("blockReason") or cand.get("finishReason")
            raise RuntimeError(f"réponse vide ({block})")
        return _parse_json(text)
    raise RuntimeError(f"Gemini refuse la requête : {last}")


def _parse_json(text: str) -> dict:
    """JSON out of a model's text: fences and words around it tolerated."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


def claude_json(system: str, content: list, schema: dict, *, effort: str = "medium", timeout: float = 900) -> dict:
    import anthropic
    blocks = [{"type": "text", "text": c} if isinstance(c, str) else
              {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                           "data": base64.b64encode(c).decode()}} for c in content]
    client = anthropic.Anthropic()
    with _gates["claude"], client.beta.messages.stream(
        model=CLAUDE_FAST if _quality == "fast" else CLAUDE_MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low" if _quality == "fast" else effort,
                       "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[{"role": "user", "content": blocks}],
    ) as stream:
        response = stream.get_final_message()
    u = response.usage
    _count("claude", response.model, (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
           + (getattr(u, "cache_creation_input_tokens", 0) or 0), u.output_tokens)
    if response.stop_reason == "refusal":
        raise RuntimeError("requête refusée")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("réponse tronquée")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def ollama_json(system: str, content: list, schema: dict, *, model: str) -> dict:
    import httpx
    text = "\n".join(c for c in content if isinstance(c, str))
    r = httpx.post("http://localhost:11434/api/chat", timeout=180, json={
        "model": model, "stream": False, "format": schema,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]})
    return json.loads(r.json()["message"]["content"])


def _cli_prompt(system: str, content: list, folder: Path) -> tuple[str, list[str]]:
    """One text for a CLI: instructions, then the message, images saved as files and named in place."""
    parts, images = [system.strip(), "", "---", ""], []
    for c in content:
        if isinstance(c, str):
            parts.append(c)
        else:
            name = f"image{len(images) + 1:02d}.jpg"
            (folder / name).write_bytes(c)
            images.append(name)
            parts.append(f"[{name}]")
    return "\n".join(parts), images


def claude_code_json(system: str, content: list, schema: dict, *, effort: str = "medium", timeout: float = 900) -> dict:
    path = exe("claude")
    if not path:
        raise RuntimeError("Claude Code n'est pas installé")
    with tempfile.TemporaryDirectory(prefix="autocut-ai-") as tmp:
        prompt, images = _cli_prompt(system, content, Path(tmp))
        if images:
            prompt += ("\n\nLes images [imageNN.jpg] sont des fichiers du dossier courant : regarde-les toutes "
                       "avec l'outil Read avant de répondre.")
        cmd = [path, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
               "--model", "sonnet" if _quality == "fast" else "opus", "--strict-mcp-config",
               "--no-session-persistence", "--tools", "Read" if images else ""]
        if images:
            cmd += ["--allowedTools", "Read"]
        with _gates["cli"]:
            # without ANTHROPIC_API_KEY, so that the subscription pays, not an API account
            r = _run(cmd, prompt, tmp, timeout, drop_env=("ANTHROPIC_API_KEY",))
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"Claude Code : {(r.stderr or r.stdout).strip()[:200]}") from None
    u = data.get("usage") or {}
    _count("claude-code", "", (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
           + (u.get("cache_creation_input_tokens") or 0), u.get("output_tokens"))
    if data.get("is_error") or "structured_output" not in data:
        raise RuntimeError(f"Claude Code : {str(data.get('result') or data.get('subtype'))[:200]}")
    return data["structured_output"]


_codex_model: dict = {}


def _codex_models(path: str) -> list[str]:
    """Models this Codex lists for the signed-in account, best first (the config may name one it refuses)."""
    if "list" not in _codex_model:
        try:
            r = _run([path, "debug", "models"], timeout=30)
            data = json.loads(r.stdout)
            models = data.get("models", data) if isinstance(data, dict) else data
            listed = sorted((m for m in models if isinstance(m, dict) and m.get("visibility") == "list"
                             and "image" in (m.get("input_modalities") or ["image"])),
                            key=lambda m: m.get("priority", 99))
            _codex_model["list"] = [m["slug"] for m in listed]
        except Exception:
            _codex_model["list"] = []
    return _codex_model["list"]


def codex_json(system: str, content: list, schema: dict, *, effort: str = "medium", timeout: float = 900) -> dict:
    path = exe("codex")
    if not path:
        raise RuntimeError("Codex n'est pas installé")
    models = _codex_models(path)
    with tempfile.TemporaryDirectory(prefix="autocut-ai-") as tmp:
        prompt, images = _cli_prompt(system, content, Path(tmp))
        if images:
            prompt += "\n\nLes images [imageNN.jpg] sont jointes, dans cet ordre."
        (Path(tmp) / "schema.json").write_text(json.dumps(_strip_schema(schema, ("minimum", "maximum"))),
                                               encoding="utf-8")
        cmd = [path, "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
               "--output-schema", "schema.json", "-o", "answer.json",
               "-c", f"model_reasoning_effort={'low' if _quality == 'fast' else effort}"]
        if models:
            cmd += ["-m", models[0]]
        for name in images:
            cmd += ["-i", name]
        cmd.append("-")
        with _gates["cli"]:
            r = _run(cmd, prompt, tmp, timeout, drop_env=("OPENAI_API_KEY",))
        answer = Path(tmp) / "answer.json"
        if r.returncode != 0 or not answer.exists():
            err = [ln for ln in (r.stderr + r.stdout).splitlines() if "ERROR" in ln or "error" in ln.lower()]
            raise RuntimeError(f"Codex : {(err[-1] if err else r.stderr.strip()[-200:])[:240]}")
        used = re.search(r"tokens used\s*\n\s*([\d,  ]+)", r.stderr + r.stdout)
        _count("codex", models[0] if models else "", int(re.sub(r"\D", "", used.group(1))) if used else 0, 0)
        return _parse_json(answer.read_text(encoding="utf-8"))


_agy_cache: dict = {}


def _agy_models(path: str, refresh: bool = False) -> list[str]:
    """Model slugs of the signed-in Antigravity account ([] when signed out)."""
    if refresh or "list" not in _agy_cache:
        try:
            r = _run([path, "models"], timeout=45)
            _agy_cache["list"] = [ln.split("\t")[0].strip() for ln in r.stdout.splitlines()
                                  if "\t" in ln and r.returncode == 0]
        except (OSError, subprocess.SubprocessError):
            _agy_cache["list"] = []
    return _agy_cache["list"]


def _agy_model(path: str) -> str:
    models = _agy_models(path)
    gem = [m for m in models if m.startswith("gemini")]
    if _quality == "fast":
        pick = [m for m in gem if "flash" in m and m.endswith("-low")] or [m for m in gem if "flash" in m]
    else:
        pick = [m for m in gem if m.endswith("-high") and "flash" not in m] or [m for m in gem if m.endswith("-high")]
    return (pick or gem or models or [""])[0]


def antigravity_json(system: str, content: list, schema: dict, *, effort: str = "medium", timeout: float = 900) -> dict:
    """Antigravity CLI in print mode. It does not read stdin and the command line is short: the request
    goes in request.md, the images next to it, and the prompt asks it to read them (reads need no approval)."""
    path = exe("agy")
    if not path:
        raise RuntimeError("Antigravity n'est pas installé")
    with tempfile.TemporaryDirectory(prefix="autocut-ai-") as tmp:
        prompt, images = _cli_prompt(system, content, Path(tmp))
        if images:
            prompt += ("\n\nLes images [imageNN.jpg] sont des fichiers de ce dossier : regarde-les toutes avant "
                       "de répondre.")
        (Path(tmp) / "request.md").write_text(prompt, encoding="utf-8")
        cmd = [path, "--output-format", "json", "--json-schema", json.dumps(schema), "--disable-slash-commands",
               "--print=Lis le fichier request.md du dossier courant et fais ce qu'il demande"
               + (", en regardant les images qu'il cite (même dossier)" if images else "")
               + ". Réponds selon le schéma JSON."]
        model = _agy_model(path)
        if model:
            cmd[1:1] = ["--model", model]
        with _gates["cli"]:
            r = _run(cmd, "", tmp, timeout)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"Antigravity : {(r.stderr or r.stdout).strip()[:240]}") from None
    u = data.get("usage") or {}
    _count("antigravity", model, u.get("input_tokens"), (u.get("output_tokens") or 0) + (u.get("thinking_tokens") or 0))
    if isinstance(data.get("structured_output"), dict):
        return data["structured_output"]
    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"Antigravity : {str(data.get('status'))} {str(data.get('response', ''))[:200]}")
    return _parse_json(str(data.get("response", "")))


def ask(engine: str, system: str, content: list, schema: dict, *, effort: str = "medium", timeout: float = 900) -> dict:
    if engine == "gemini":
        return gemini_json(system, content, schema, timeout=timeout)
    if engine == "claude":
        return claude_json(system, content, schema, effort=effort, timeout=timeout)
    if engine == "claude-code":
        return claude_code_json(system, content, schema, effort=effort, timeout=timeout)
    if engine == "codex":
        return codex_json(system, content, schema, effort=effort, timeout=timeout)
    if engine == "antigravity":
        return antigravity_json(system, content, schema, effort=effort, timeout=timeout)
    if engine == "ollama":
        model = ollama_available()
        if not model:
            raise RuntimeError("Ollama n'est pas lancé")
        return ollama_json(system, content, schema, model=model)
    raise ValueError(engine)


# --- Installing the CLIs (from the window, on the user's click) -------------------------------------

INSTALL = {
    "claude-code": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    "irm https://claude.ai/install.ps1 | iex"],
    "codex": ["npm", "install", "-g", "@openai/codex"],
    "antigravity": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    "irm https://antigravity.google/cli/install.ps1 | iex"],
}
HELP_URL = {"codex": "https://developers.openai.com/codex/cli", "claude-code": "https://code.claude.com/docs/en/setup",
            "antigravity": "https://antigravity.google", "ollama": "https://ollama.com/download",
            "gemini": "https://aistudio.google.com/apikey", "claude": "https://console.anthropic.com/settings/keys"}


def install(engine: str) -> None:
    cmd = list(INSTALL[engine])
    if cmd[0] == "npm":
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            raise SystemExit("Node.js manque (nodejs.org) : installez-le, puis recommencez.")
        cmd[0] = npm
    print(f"[1/1] installation : {' '.join(cmd[-3:])}")
    subprocess.run(cmd, check=True)

