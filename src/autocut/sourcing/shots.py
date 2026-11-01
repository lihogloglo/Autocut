"""4K screenshots of cited pages: top of page, the supporting passage, and the same passage highlighted.

Runs Playwright on the Edge that ships with Windows (no browser download). Playwright's sync API
is bound to one thread, so all pages go through a single worker fed by a queue."""

from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

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
  }
  for (const el of [document.documentElement, document.body]) {
    el.style.setProperty('overflow', 'auto', 'important');
    el.style.setProperty('position', 'static', 'important');
  }
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

SCROLL_JS = """([i, top]) => {
  const el = document.querySelector(`[data-ac-idx="${i}"]`);
  if (!el) return;
  const r = el.getBoundingClientRect();
  window.scrollBy(0, r.top - (r.height < innerHeight * 0.6 ? innerHeight * 0.38 : innerHeight * 0.12));
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


def _shoot(ctx: Ctx, page, job: Job, log) -> list[Asset]:
    key = Asset.make_id(job.url)
    folder = ctx.out / "captures"
    folder.mkdir(parents=True, exist_ok=True)
    page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("load", timeout=12000)
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
        a = Asset(id=Asset.make_id("capture", job.url, path.name, s.idx), kind="screenshot", via="capture",
                  origin="lien", sentence=s.idx, paragraph=s.paragraph, url=job.url, file=ctx.rel(path),
                  thumb=thumb(ctx, path), source_page=job.url, title=f"{title} — {what}", author=host,
                  rights=QUOTE, width=3840, height=2160, note=note)
        return a

    out = []
    top = folder / f"{key}_haut.jpg"
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)
    page.screenshot(path=top, type="jpeg", quality=90)
    first = job.cites[0][0]
    out.append(asset(top, first, "haut de page"))
    done = {}
    for s, link in job.cites:
        idx, score = _passage(s, link, blocks)
        if idx is None:
            continue
        note = "" if score >= 0.45 else "passage incertain : vérifier le surlignage"
        if idx not in done:
            page.evaluate(SCROLL_JS, [idx, 0])
            page.wait_for_timeout(900)
            plain = folder / f"{key}_{idx}_passage.jpg"
            mark = folder / f"{key}_{idx}_surligne.jpg"
            page.screenshot(path=plain, type="jpeg", quality=90)
            page.evaluate(MARK_JS, [idx, True])
            page.screenshot(path=mark, type="jpeg", quality=90)
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

    def __init__(self, ctx: Ctx, log=print):
        super().__init__(daemon=True)
        self.ctx, self.log = ctx, log
        self.jobs: queue.Queue = queue.Queue()
        self.assets: list[Asset] = []
        self.done = 0

    def run(self) -> None:
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(channel="msedge")
                except Exception:
                    browser = p.chromium.launch()
                context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=2,
                                              locale="fr-FR", accept_downloads=False)
                while (job := self.jobs.get()) is not None:
                    page = context.new_page()
                    try:
                        self.assets += _shoot(self.ctx, page, job, self.log)
                    except Exception as e:
                        self.ctx.errors.append({"url": job.url, "error": f"capture : {type(e).__name__} {str(e)[:120]}"})
                    finally:
                        page.close()
                        self.done += 1
                browser.close()
        except Exception as e:
            self.ctx.errors.append({"url": "", "error": f"captures impossibles : {e}"})
            while self.jobs.get() is not None:
                pass
