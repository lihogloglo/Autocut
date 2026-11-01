"""Tall screenshots of cited pages (3840 px wide, taller than the screen so the edit can pan):
top of page, the supporting passage, and the same passage highlighted.

Runs Playwright on the Edge that ships with Windows (no browser download). Playwright's sync API
is bound to one thread, so all pages go through a single worker fed by a queue."""

from __future__ import annotations

import os
import queue
import re
import threading
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from PIL import Image

from . import embed
from .collect import Ctx, thumb
from .model import QUOTE, Asset
from .script import Link, ScriptSentence

CONSENT_SELECTORS = [
    "#didomi-notice-agree-button", "#onetrust-accept-btn-handler", ".fc-cta-consent", "#axeptio_btn_acceptAll",
    "[data-testid='uc-accept-all-button']", "#tarteaucitronPersonalize2", ".sd-cmp-JnaLO", "#cmpbntyestxt",
    "button.sp_choice_type_11", "#acceptAllButton", ".cmp-intro_acceptAll", "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#truste-consent-button", "button[data-cookiebanner='accept_button']", ".qc-cmp2-summary-buttons button[mode='primary']",
]
CONSENT_TEXT = re.compile(r"^\s*(tout accepter|accepter( et fermer| tout| les cookies)?|j'accepte|ok,? j'accepte|"
                          r"accept( all)?( cookies)?|yes,? i accept|i accept|i agree|agree|allow all|autoriser|"
                          r"continuer sans accepter|got it|ok)\s*$", re.I)

CLEAN_JS = """() => {
  const vw = innerWidth, vh = innerHeight;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const area = (r.width * r.height) / (vw * vh);
    const txt = (el.innerText || '').slice(0, 600).toLowerCase();
    if (area > 0.25 || r.top > vh * 0.45 ||
        /cookie|consent|newsletter|abonnez|subscribe|privacy|confidentialit|publicit|adblock/.test(txt))
      el.style.setProperty('display', 'none', 'important');
    else   // a header that follows the scroll would float mid-capture: pin it to the top of the page
      el.style.setProperty('position', cs.position === 'fixed' ? 'absolute' : 'relative', 'important');
  }
  // Undo the scroll lock of cookie walls without making <body> its own scroller
  // (overflow:auto on both html and body does that, and then the window no longer scrolls).
  for (const el of [document.documentElement, document.body]) {
    if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.overflowY === 'hidden') el.style.setProperty('overflow-y', 'visible', 'important');
    if (cs.position === 'fixed') el.style.setProperty('position', 'static', 'important');
  }
  document.documentElement.style.setProperty('scroll-behavior', 'auto', 'important');
}"""

BLOCKS_JS = """(frag) => {
  let anchor = null, stop = null;
  if (frag) {
    anchor = document.getElementById(frag) || document.getElementsByName(frag)[0] || null;
    if (anchor) {
      const h = anchor.closest('h1,h2,h3,h4,h5,h6') || anchor.querySelector('h1,h2,h3,h4,h5,h6') || anchor;
      const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')];
      const level = /^H\\d$/.test(h.tagName) ? +h.tagName[1] : 6;
      const at = heads.indexOf(h);
      if (at >= 0) stop = heads.slice(at + 1).find(x => +x.tagName[1] <= level) || null;
      anchor = h;
    }
  }
  const out = [];
  document.querySelectorAll('p, li, blockquote, figcaption, td, dd, h1, h2, h3').forEach((el, i) => {
    if (el.closest('nav, footer, header, aside, [role=navigation], [role=banner], .navbox, .reflist, .references'))
      return;
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 8) return;
    const t = el.innerText.trim();
    if (t.length < 25 || t.length > 2500) return;
    if ([...el.querySelectorAll('p, li')].length > 0 && el.tagName !== 'LI') return;   // keep the innermost blocks
    let inSection = false;
    if (anchor) {
      inSection = !!(anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) &&
                  (!stop || !!(stop.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING));
    }
    el.dataset.acIdx = i;
    out.push([i, t, inSection]);
  });
  return [out, anchor ? 1 : 0, document.title];
}"""

RECT_JS = """(i) => {
  const doc = document.scrollingElement || document.documentElement;
  const docH = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const el = i == null ? null : document.querySelector(`[data-ac-idx="${i}"]`);
  if (!el) return [0, 0, docH];
  const r = el.getBoundingClientRect();
  return [r.top + scrollY, r.height, docH];
}"""

# Pages that scroll inside an element rather than the window can only be captured at screen height:
# the passage is scrolled into view there instead.
INNER_SCROLL_JS = """(i) => {
  const el = document.querySelector(`[data-ac-idx="${i}"]`);
  if (el) el.scrollIntoView({block: 'center', behavior: 'instant'});
}"""

MARK_JS = """([i, on]) => {
  const el = document.querySelector(`[data-ac-idx="${i}"]`);
  if (!el) return;
  if (on) {
    el.dataset.acStyle = el.getAttribute('style') || '';
    el.style.setProperty('background', 'rgba(255, 214, 0, 0.6)', 'important');
    el.style.setProperty('box-shadow', '0 0 0 8px rgba(255, 214, 0, 0.6)', 'important');
    el.style.setProperty('border-radius', '2px', 'important');
  } else {
    el.setAttribute('style', el.dataset.acStyle || '');
  }
}"""


@dataclass
class Job:
    url: str
    cites: list[tuple[ScriptSentence, Link]]


def _dismiss_consent(page) -> None:
    for frame in page.frames:
        for sel in CONSENT_SELECTORS:
            try:
                loc = frame.locator(sel)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=1500)
                    page.wait_for_timeout(700)
                    return
            except Exception:
                pass
    for frame in page.frames:
        try:
            buttons = frame.get_by_role("button", name=CONSENT_TEXT)
            if buttons.count():
                buttons.first.click(timeout=1500)
                page.wait_for_timeout(700)
                return
        except Exception:
            pass


def _passage(s: ScriptSentence, link: Link, blocks: list) -> tuple[int | None, float]:
    if not blocks:
        return None, 0.0
    texts = [b[1] for b in blocks]
    sims = embed.similarity(s.text, texts)
    figs = embed.numbers(s.text)
    anchor = link.anchor.lower().strip()
    best, best_score = None, -1.0
    for (i, text, in_section), sim in zip(blocks, sims):
        score = float(sim) + 0.12 * len(figs & embed.numbers(text)) + 0.25 * in_section
        if len(anchor) > 3 and anchor in text.lower():
            score += 0.15
        score -= 0.05 * (len(text) > 1200)
        if score > best_score:
            best, best_score = i, score
    return best, best_score


def _capture(page, path, idx: int | None, tall: int) -> None:
    """`tall` page pixels from the top of the page, or around block `idx` (at ~40 % of the height)."""
    view_h = page.viewport_size["height"]
    _, _, doc_h = page.evaluate(RECT_JS, None)
    if doc_h <= view_h + 40:          # nothing scrolls the window: inner scroller, or a short page
        if idx is not None:
            page.evaluate(INNER_SCROLL_JS, idx)
            page.wait_for_timeout(700)
        page.screenshot(path=path, type="jpeg", quality=88)
        return
    y = 0.0
    if idx is not None:
        top, h, _ = page.evaluate(RECT_JS, idx)
        y = top - 120 if h > tall * 0.7 else top + h / 2 - tall * 0.4
    height = min(tall, doc_h)
    y = int(max(0, min(y, doc_h - height)))
    for at in range(y, y + height, view_h // 2):     # walk through the region so lazy images load
        page.evaluate("y => window.scrollTo(0, y)", at)
        page.wait_for_timeout(120)
    page.evaluate("y => window.scrollTo(0, y)", y)
    page.wait_for_timeout(600)
    page.screenshot(path=path, type="jpeg", quality=88, full_page=True,
                    clip={"x": 0, "y": y, "width": page.viewport_size["width"], "height": height})


def _shoot(ctx: Ctx, page, job: Job, log, tall: int = 2400) -> list[Asset]:
    key = Asset.make_id(job.url)
    folder = ctx.out / "captures"
    folder.mkdir(parents=True, exist_ok=True)
    page.goto(job.url, wait_until="commit", timeout=45000)
    for state, ms in (("domcontentloaded", 30000), ("load", 12000)):
        try:
            page.wait_for_load_state(state, timeout=ms)
        except Exception:
            pass
    page.wait_for_timeout(1500)
    _dismiss_consent(page)
    page.evaluate(CLEAN_JS)
    page.wait_for_timeout(300)
    frag = unquote(urlparse(job.url).fragment) or None
    blocks, has_anchor, title = page.evaluate(BLOCKS_JS, frag)
    title = (title or urlparse(job.url).netloc)[:120]
    host = urlparse(job.url).netloc

    def asset(path, s, what, note=""):
        with Image.open(path) as im:
            w, h = im.size
        return Asset(id=Asset.make_id("capture", job.url, path.name, s.idx), kind="screenshot", via="capture",
                     origin="lien", sentence=s.idx, paragraph=s.paragraph, url=job.url, file=ctx.rel(path),
                     thumb=thumb(ctx, path), source_page=job.url, title=f"{title} — {what}", author=host,
                     rights=QUOTE, width=w, height=h, note=note)

    out = []
    top = folder / f"{key}_haut.jpg"
    _capture(page, top, None, tall)
    first = job.cites[0][0]
    out.append(asset(top, first, "haut de page"))
    done = {}
    for s, link in job.cites:
        idx, score = _passage(s, link, blocks)
        if idx is None:
            continue
        note = "" if score >= 0.45 else "passage incertain : vérifier le surlignage"
        if idx not in done:
            plain = folder / f"{key}_{idx}_passage.jpg"
            mark = folder / f"{key}_{idx}_surligne.jpg"
            _capture(page, plain, idx, tall)
            page.evaluate(MARK_JS, [idx, True])
            _capture(page, mark, idx, tall)
            page.evaluate(MARK_JS, [idx, False])
            done[idx] = (plain, mark)
        plain, mark = done[idx]
        a, b = asset(plain, s, "passage", note), asset(mark, s, "passage surligné", note)
        a.score = b.score = round(score, 3) + 0.3
        out += [b, a]
        if s is not first:
            out.append(asset(top, s, "haut de page"))
    return out


class ScreenshotWorker(threading.Thread):
    """Takes Jobs from a queue until None, collects assets in .assets."""

    def __init__(self, ctx: Ctx, log=print, height: int = 2400):
        super().__init__(daemon=True)
        self.ctx, self.log = ctx, log
        self.height = height          # capture height in page pixels (x2 in the image)
        self.jobs: queue.Queue = queue.Queue()
        self.assets: list[Asset] = []
        self.done = 0

    def run(self) -> None:
        from playwright.sync_api import sync_playwright
        # Don't wait for web fonts before a screenshot: some sites (insee.fr) never finish loading one.
        os.environ.setdefault("PW_TEST_SCREENSHOT_NO_FONTS_READY", "1")
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(channel="msedge")
                except Exception:
                    browser = p.chromium.launch()
                context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=2,
                                              locale="fr-FR", accept_downloads=False)
                failed: dict[str, int] = {}   # host -> failures: a site that blocks browsers blocks them all
                while (job := self.jobs.get()) is not None:
                    host = urlparse(job.url).netloc
                    if failed.get(host, 0) >= 2:
                        self.ctx.errors.append({"url": job.url, "error": "capture : site qui bloque le navigateur, ignoré"})
                        self.done += 1
                        continue
                    page = context.new_page()
                    try:
                        self.assets += _shoot(self.ctx, page, job, self.log, self.height)
                    except Exception as e:
                        failed[host] = failed.get(host, 0) + 1
                        self.ctx.errors.append({"url": job.url, "error": f"capture : {type(e).__name__} {str(e)[:120]}"})
                    finally:
                        page.close()
                        self.done += 1
                browser.close()
        except Exception as e:
            self.ctx.errors.append({"url": "", "error": f"captures impossibles : {e}"})
            while self.jobs.get() is not None:
                pass
