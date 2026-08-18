#!/usr/bin/env python3
"""Perchance: extract iframe src, navigate to it, dump content."""
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
ws = D.WS(tab["webSocketDebuggerUrl"])
try:
    time.sleep(8)
    info = D.evaluate(ws, r"""
(() => {
  const iframes = Array.from(document.querySelectorAll('iframe')).map(f => f.src);
  return JSON.stringify({iframes, links: Array.from(document.querySelectorAll('a')).map(a=>a.href).filter(h=>h.includes('perchance')).slice(0,40)});
})()
""")
    print("iframes/links:", str(info)[:600])
    # navigate to the first iframe src
    iframes = json.loads(info or "{}").get("iframes", [])
    target = next((f for f in iframes if f.startswith("http")), None)
    if target:
        D.evaluate(ws, f"location.href = {json.dumps(target)}")
        time.sleep(8)
        body = D.evaluate(ws, "document.body ? document.body.innerText : ''") or ""
        print("iframe content chars:", len(body))
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({"url": target, "text": body[:60000]}, f, ensure_ascii=False, indent=1)
        print("SAVED")
    else:
        print("no iframe found")
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])
