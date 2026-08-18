#!/usr/bin/env python3
"""Open a URL in Comet (new tab), wait for Cloudflare to pass, dump page text.
Usage: python perchance_cdp.py <url>
Output: C:\\Users\\jay\\AppData\\Local\\Temp\\perchance_dump.json
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
print("tab:", tab.get("id", "?")[:12], tab.get("url", "")[:70])
ws = D.WS(tab["webSocketDebuggerUrl"])
try:
    # wait for Cloudflare to clear
    for i in range(15):
        time.sleep(3)
        title = D.evaluate(ws, "document.title")
        if title and "Just a moment" not in title and title != "about:blank":
            break
    time.sleep(3)
    # wait for SPA content to render (beyond the 67-char chrome nav)
    for i in range(20):
        body = D.evaluate(ws, "document.body ? document.body.innerText : ''")
        if len(body or '') > 200:
            break
        time.sleep(3)
    body = D.evaluate(ws, "document.body ? document.body.innerText : ''")
    text = (body or "")[:60000]
    tareas = D.evaluate(ws, r"JSON.stringify(Array.from(document.querySelectorAll('textarea, [contenteditable=true], [class*=editor], [class*=CodeMirror]')).map(e => (e.value || e.innerText || '').slice(0, 60000)))")
    print("title:", title, "| body chars:", len(text), "| textareas:", len(tareas or "[]") > 2)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"url": URL, "title": title, "text": text, "editors": tareas}, f, ensure_ascii=False, indent=1)
    print("SAVED:", OUT)
finally:
    ws.close()
    close_tab(tab["id"])
