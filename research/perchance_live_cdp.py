#!/usr/bin/env python3
"""Load a Perchance generator page in Comet, poll until the SPA renders, dump text.
Usage: python perchance_live_cdp.py <url>
"""
import json, sys, os, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_cdp as D

URL = sys.argv[1]
OUT = r"C:\Users\jay\AppData\Local\Temp\perchance_dump.json"

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
best = ""
try:
    for i in range(20):
        time.sleep(4)
        try:
            body = D.evaluate(ws, "document.body ? document.body.innerText : ''") or ""
            links = D.evaluate(ws, r"JSON.stringify(Array.from(document.querySelectorAll('a')).map(a=>a.href).filter(h=>h.includes('perchance')).slice(0,20))") or "[]"
            if len(body) > len(best): best = body
            print(f"  poll {i}: body={len(body)} links={len(links)}")
            if len(body) > 500:
                break
        except Exception as e:
            print(f"  poll {i}: err {e}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"url": URL, "text": best[:60000]}, f, ensure_ascii=False, indent=1)
    print("SAVED chars:", len(best))
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])
