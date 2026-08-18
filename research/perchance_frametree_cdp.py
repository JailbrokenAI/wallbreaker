#!/usr/bin/env python3
"""Perchance scrape via CDP frame tree: reach EVERY frame (incl cross-origin) by frameId.
Usage: python perchance_frametree_cdp.py <url>
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
print("tab:", tab.get("id", "?")[:12], "|", URL[:80])
ws = D.WS(tab["webSocketDebuggerUrl"])
frames = []
texts = []
try:
    time.sleep(8)
    # enable runtime FIRST so we catch existing contexts
    ws.send({"id": 2, "method": "Runtime.enable"})
    ctxs = {}
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            ws.settimeout(0.5)
            msg = ws.recv()
        except Exception:
            continue
        if msg.get("method") == "Runtime.executionContextCreated":
            c = msg["params"]["context"]
            ctxs[c.get("auxData", {}).get("frameId", "")] = c["id"]
    print("exec contexts after enable:", len(ctxs))
    # then get frame tree (may include newly-loaded iframes)
    ws.send({"id": 1, "method": "Page.getFrameTree"})
    while True:
        msg = ws.recv()
        if msg.get("id") == 1:
            tree = msg.get("result", {}).get("frameTree", {})
            break
    # flatten
    stack = [tree]
    while stack:
        node = stack.pop()
        f = node.get("frame", {})
        frames.append(f)
        for ch in node.get("childFrames", []):
            stack.append(ch)
    print("frames:", len(frames))
    for i, f in enumerate(frames):
        fid = f.get("id", "")
        url = f.get("url", "")[:100]
        print(f"  frame {i}: {fid[:12]} {url}")
    next_id = 100
    for i, f in enumerate(frames):
        fid = f.get("id", "")
        cid = ctxs.get(fid)
        if cid is None:
            print(f"  frame {i}: no context")
            continue
        next_id += 1
        expr = "document.body ? document.body.innerText : ''"
        ws.send({"id": next_id, "method": "Runtime.evaluate",
                 "params": {"expression": expr, "contextId": cid,
                            "returnByValue": True, "awaitPromise": True}})
        try:
            ws.settimeout(10)
            msg = ws.recv()
            if msg.get("id") == next_id:
                val = msg.get("result", {}).get("result", {}).get("value", "")
                texts.append({"frame": i, "url": f.get("url", "")[:200], "text": (val or "")[:40000]})
                print(f"  frame {i} text chars: {len(val or '')}")
        except Exception as e:
            print(f"  frame {i} err {e}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"url": URL, "frames": texts}, f, ensure_ascii=False, indent=1)
    print("SAVED")
finally:
    try: ws.close()
    except Exception: pass
    close_tab(tab["id"])
