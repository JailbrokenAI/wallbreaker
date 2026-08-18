#!/usr/bin/env python3
"""Open a Perchance generator EDITOR in Comet and dump its source code.
Usage: python perchance_edit_cdp.py <generator-name-or-url>
Output: C:\\Users\\jay\\AppData\\Local\\Temp\\perchance_dump.json
"""
import json, sys, os, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_cdp as D

arg = sys.argv[1]
if arg.startswith("http"):
    url = arg
else:
    url = f"https://perchance.org/edit?generator={urllib.parse.quote(arg, safe='')}"
OUT = r"C:\Users\jay\AppData\Local\Temp\perchance_dump.json"

def new_tab(url):
    req = urllib.request.Request(f"{D.CDP}/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)

def close_tab(tab_id):
    try: urllib.request.urlopen(f"{D.CDP}/json/close/{tab_id}", timeout=5).read()
    except Exception: pass

tab = new_tab(url)
print("tab:", tab.get("id", "?")[:12], "|", url[:80])
ws = D.WS(tab["webSocketDebuggerUrl"])
title = ""
try:
    for i in range(15):
        time.sleep(3)
        try: title = D.evaluate(ws, "document.title")
        except Exception: pass
        if title and "Just a moment" not in str(title) and str(title) != "None":
            break
    # poll for editor source: CodeMirror content / textarea / .cm-content
    source = ""
    for i in range(15):
        try:
            source = D.evaluate(ws, r"""
(() => {
  const sel = ['.cm-content', '.CodeMirror-code', 'textarea', '[contenteditable="true"]', 'pre.cm-line'];
  for (const s of sel) {
    const el = document.querySelector(s);
    if (el) {
      const t = s === 'textarea' ? (el.value || '') : (el.innerText || el.textContent || '');
      if (t && t.length > 50) return t.slice(0, 50000);
    }
  }
  return document.body ? document.body.innerText.slice(0, 50000) : '';
})()
""")
        except Exception:
            source = None
        if source and len(source) > 200:
            break
        time.sleep(3)
    print("title:", title, "| source chars:", len(source or ""))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"url": url, "title": title, "source": source or ""}, f, ensure_ascii=False, indent=1)
    print("SAVED:", OUT)
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])
