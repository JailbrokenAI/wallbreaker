#!/usr/bin/env python3
"""Perchance PATIENT scrape: stay on the generator subdomain page, poll until the
same-origin content iframe loads (Cloudflare challenge inside needs time), then
extract the full generator output text and the raw source if reachable.
Usage: python perchance_patient_cdp.py <subdomain-url>
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
result = {"url": URL, "inner_iframe_text": "", "all_text": ""}
try:
    best = ""
    for i in range(30):  # up to ~150s
        time.sleep(5)
        try:
            # Try to read same-origin inner iframe contentDocument directly
            info = D.evaluate(ws, r"""
(() => {
  const ifs = Array.from(document.querySelectorAll('iframe')).filter(f => f.src && f.src.includes('perchance.'));
  let innerText = null, src = null, ready = null;
  for (const f of ifs) {
    try {
      if (f.contentDocument && f.contentDocument.body) {
        src = f.src; ready = true;
        innerText = f.contentDocument.body.innerText.slice(0, 50000);
        break;
      }
    } catch(e) { ready = false; }
  }
  return JSON.stringify({iframeCount: ifs.length, ready, src, innerLen: innerText ? innerText.length : 0, innerText});
})()
""")
            parsed = json.loads(info or "{}")
            inner = parsed.get("innerText") or ""
            if len(inner) > len(best):
                best = inner
                if len(inner) > 500:
                    print(f"  poll {i}: content loaded, chars={len(inner)}")
                    result["inner_iframe_text"] = inner
                    break
            # fallback: whole page text
            body = D.evaluate(ws, "document.body ? document.body.innerText : ''") or ""
            if len(body) > len(result["all_text"]):
                result["all_text"] = body
            print(f"  poll {i}: iframes={parsed.get('iframeCount')} ready={parsed.get('ready')} inner={parsed.get('innerLen')} body={len(body)}")
        except Exception as e:
            print(f"  poll {i}: err {e}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("SAVED chars:", len(result["inner_iframe_text"]), "| all_text:", len(result["all_text"]))
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])