#!/usr/bin/env python3
"""Perchance: fetch full generator HTML from page context (1.4MB), save raw + mine markers.
Usage: python perchance_fetch_cdp.py <url>
"""
import json, sys, os, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_cdp as D

URL = sys.argv[1]
OUT = r"C:\Users\jay\AppData\Local\Temp\perchance_full.json"

def new_tab(url):
    req = urllib.request.Request(f"{D.CDP}/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)

def close_tab(tab_id):
    try: urllib.request.urlopen(f"{D.CDP}/json/close/{tab_id}", timeout=5).read()
    except Exception: pass

tab = new_tab(URL)
print("tab:", tab.get("id", "?")[:12])
ws = D.WS(tab["webSocketDebuggerUrl"])
try:
    time.sleep(6)
    fetched = D.evaluate(ws, r"""
(async () => {
  try {
    const r = await fetch(location.href, {credentials: 'include'});
    const t = await r.text();
    return t;
  } catch(e) { return 'ERR ' + e.message; }
})()
""")
    if fetched and not str(fetched).startswith("ERR"):
        print("fetched chars:", len(fetched))
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({"url": URL, "html": fetched}, f, ensure_ascii=False)
        print("SAVED raw html")
    else:
        print("fetch failed:", str(fetched)[:200])
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])