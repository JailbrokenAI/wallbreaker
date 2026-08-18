#!/usr/bin/env python3
"""Perchance deep diagnostic: dump iframe tree + full HTML of each frame, try contentDocument.
Usage: python perchance_deep_cdp.py <url>
"""
import json, sys, os, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_cdp as D

URL = sys.argv[1]
OUT = r"C:\Users\jay\AppData\Local\Temp\perchance_deep.json"

def new_tab(url):
    req = urllib.request.Request(f"{D.CDP}/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)

def close_tab(tab_id):
    try: urllib.request.urlopen(f"{D.CDP}/json/close/{tab_id}", timeout=5).read()
    except Exception: pass

tab = new_tab(URL)
print("tab:", tab.get("id", "?")[:12], "|", URL[:80])
ws = D.WS(tab["webSocketDebuggerUrl"])
result = {"url": URL, "frames": [], "html_head": ""}
try:
    time.sleep(10)
    # Walk all frames recursively (same-origin only), collect src + innerText + html
    expr = r"""
(() => {
  const out = [];
  const walk = (doc, depth) => {
    if (!doc) return;
    const ifs = Array.from(doc.querySelectorAll('iframe'));
    ifs.forEach(f => {
      const rec = {depth, src: f.src || '', w: f.offsetWidth, h: f.offsetHeight};
      let inner = null;
      try {
        if (f.contentDocument) {
          rec.docText = (f.contentDocument.body ? f.contentDocument.body.innerText : '').slice(0, 3000);
          rec.docLen = f.contentDocument.body ? f.contentDocument.body.innerText.length : 0;
          inner = f.contentDocument;
        } else {
          rec.docText = null; // cross-origin
        }
      } catch(e) { rec.docText = 'ERR ' + e.message; }
      out.push(rec);
      walk(inner, depth + 1);
    });
  };
  walk(document, 0);
  return JSON.stringify(out);
})()
"""
    tree = D.evaluate(ws, expr)
    print("frame tree:", str(tree)[:2000])
    result["frames"] = json.loads(tree or "[]")
    # dump main doc html head for structure clues
    html = D.evaluate(ws, "(document.documentElement ? document.documentElement.outerHTML : '').slice(0, 8000)")
    result["html_head"] = (html or "")[:8000]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("SAVED")
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])
