#!/usr/bin/env python3
"""Perchance: dump full HTML of subdomain page + try fetch() of generator URL from page context.
Usage: python perchance_html_cdp.py <url>
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
print("tab:", tab.get("id", "?")[:12])
ws = D.WS(tab["webSocketDebuggerUrl"])
result = {}
try:
    time.sleep(10)
    # 1. full outer HTML of the subdomain page (what is this page really?)
    html = D.evaluate(ws, "document.documentElement ? document.documentElement.outerHTML.slice(0, 20000) : ''") or ""
    result["html_head_2k"] = html[:2000]
    # 2. look for any cloudflare markers
    cf = D.evaluate(ws, r"JSON.stringify({title: document.title, hasTurnstile: !!document.querySelector('iframe[src*=challenges], .cf-turnstile'), bodyClasses: document.body ? document.body.className : ''})") or ""
    result["page_info"] = cf
    # 3. try fetch() of the generator URL from page context (may be CORS-blocked or same-origin)
    fetched = D.evaluate(ws, r"""
(async () => {
  try {
    const r = await fetch(location.href, {credentials: 'include'});
    const t = await r.text();
    return JSON.stringify({ok: r.ok, status: r.status, len: t.length, head: t.slice(0, 1500)});
  } catch(e) { return JSON.stringify({err: e.message}); }
})()
""")
    result["fetch"] = fetched
    print("page_info:", str(cf)[:300])
    print("fetch:", str(fetched)[:300])
    print("html_head:", html[:500].replace("\n", " "))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("SAVED")
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])