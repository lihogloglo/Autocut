"use strict";
// Interface language, shared by the window, the planche and the storyboard page (and the Premiere panel).
// The French text is the key; the catalogue (locales/<lang>/*.json) gives the translation.
//   t("Exporter la sélection")             -> "Export the selection"
//   t("{n} sélectionné(s)", {n: 3})         -> "3 selected"
// Static text needs nothing: text nodes and placeholder / title / aria-label attributes whose whole text
// is a key are translated when they appear in the page (also after innerHTML updates).
(function () {
  const I18N = window.I18N = { lang: "fr", dict: {} };
  const ATTRS = ["placeholder", "title", "aria-label", "data-tip"];
  const fill = (s, v) => (v ? s.replace(/\{(\w+)\}/g, (m, k) => (k in v ? v[k] : m)) : s);

  window.t = (s, v) => fill((I18N.dict[s] ?? s), v);

  function node(n) {
    if (n.nodeType === 3) {
      const raw = n.nodeValue, key = raw.trim();
      const tr = key && I18N.dict[key];
      if (tr && tr !== key) n.nodeValue = raw.replace(key, tr);     // same text: no write (it would loop)
      return;
    }
    if (n.nodeType !== 1 || n.nodeName === "SCRIPT" || n.nodeName === "STYLE" || n.closest?.("[data-noi18n]")) return;
    for (const a of ATTRS) {
      const v = n.getAttribute && n.getAttribute(a);
      const tr = v && I18N.dict[v.trim()];
      if (tr && tr !== v.trim()) n.setAttribute(a, tr);
    }
    for (const c of n.childNodes) node(c);
  }
  I18N.apply = (root = document.documentElement) => { if (I18N.lang !== "fr") node(root); };

  let observer;
  I18N.set = (lang, dict) => {
    I18N.lang = lang || "fr";
    I18N.dict = dict || {};
    document.documentElement.lang = I18N.lang;
    if (I18N.lang === "fr") return;
    I18N.apply();
    if (!observer) {
      observer = new MutationObserver((muts) => {
        for (const m of muts) {
          if (m.type === "characterData") node(m.target);
          else if (m.type === "attributes") node(m.target);
          else for (const n of m.addedNodes) node(n);
        }
      });
      observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true,
                                                    attributes: true, attributeFilter: ATTRS });
    }
  };
  if (window.I18N_INIT) {
    I18N.lang = I18N_INIT.lang; I18N.dict = I18N_INIT.dict;
    const go = () => I18N.set(I18N_INIT.lang, I18N_INIT.dict);
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go); else go();
  }
})();
