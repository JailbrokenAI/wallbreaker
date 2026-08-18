#!/usr/bin/env python3
"""Scrape open Discord channels via Comet CDP (127.0.0.1:9222, Windows side).
Runs on Windows python. Output: JSON to C:\\Users\\jay\\AppData\\Local\\Temp\\discord-scrape.json
Uses a minimal raw-socket WebSocket client (no external deps).
"""
import json, socket, base64, hashlib, os, struct, time, urllib.request

CDP = "http://127.0.0.1:9222"
OUT = r"C:\Users\jay\AppData\Local\Temp\discord-scrape.json"
TARGET_CHANNELS = ["jailbreaking", "general-chat"]

# ---------- minimal WebSocket client ----------
class WS:
    def __init__(self, url):
        # url: ws://host:port/path
        from urllib.parse import urlparse
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path or "/"
        req = (f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        resp = self._recv_exact_until_header()
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WS handshake failed: {resp[:120]!r}")

    def _recv_exact_until_header(self):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk: break
            buf += chunk
        return buf

    def send(self, payload: dict):
        data = json.dumps(payload).encode()
        mask = os.urandom(4)
        n = len(data)
        header = bytearray([0x81])
        if n < 126: header.append(0x80 | n)
        elif n < 65536: header.append(0x80 | 126); header += struct.pack(">H", n)
        else: header.append(0x80 | 127); header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def recv(self, timeout=15):
        self.sock.settimeout(timeout)
        try:
            hdr = self._recv_exact(2)
        except socket.timeout:
            return None
        if len(hdr) < 2: return None
        opcode = hdr[0] & 0x0F
        ln = hdr[1] & 0x7F
        if ln == 126: ln = struct.unpack(">H", self._recv_exact(2))[0]
        elif ln == 127: ln = struct.unpack(">Q", self._recv_exact(8))[0]
        if opcode == 8:  # close
            return None
        data = b""
        while len(data) < ln:
            data += self._recv_exact(ln - len(data))
        return json.loads(data) if data else None

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk: raise ConnectionError("closed")
            buf += chunk
        return buf

    def close(self):
        try: self.sock.close()
        except Exception: pass

# ---------- CDP ----------
def get_tabs():
    with urllib.request.urlopen(f"{CDP}/json/list", timeout=5) as r:
        return json.load(r)

def find_discord_tab():
    tabs = get_tabs()
    for t in tabs:
        if "discord.com" in t.get("url", ""):
            return t
    return None

def evaluate(ws, expr, await_promise=True):
    msg_id = int(time.time() * 1000) % 1000000
    ws.send({"id": msg_id, "method": "Runtime.evaluate",
             "params": {"expression": expr, "returnByValue": True, "awaitPromise": await_promise}})
    while True:
        m = ws.recv()
        if m and m.get("id") == msg_id:
            r = m.get("result", {})
            if "exceptionDetails" in r:
                return {"__error__": r["exceptionDetails"].get("text", "")}
            return r.get("result", {}).get("value")

# ---------- extraction JS ----------
SIDEBAR_JS = r"""
(() => {
  const out = [];
  document.querySelectorAll('a[href*="/channels/"]').forEach(a => {
    const m = a.href.match(/\/channels\/(\d+)\/(\d+)/);
    const txt = (a.getAttribute('aria-label') || a.innerText || '').trim();
    if (m && txt) out.push({name: txt.split('\n')[0], guild: m[1], channel: m[2]});
  });
  return JSON.stringify({channels: out, url: location.href});
})()
"""

CLICK_JS = r"""
(() => {
  const target = %s;
  const norm = s => s.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  let best = null;
  document.querySelectorAll('a[href*="/channels/"]').forEach(a => {
    const txt = norm(a.getAttribute('aria-label') || a.innerText || '');
    if (norm(target) && txt.includes(norm(target)) && a.offsetParent !== null) best = a;
  });
  if (best) { best.click(); return 'clicked'; }
  return 'notfound';
})()
"""

SIDEBAR_NORM = r"""
(() => {
  const norm = s => s.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  const out = [];
  document.querySelectorAll('a[href*="/channels/"]').forEach(a => {
    const m = a.href.match(/\/channels\/(\d+)\/(\d+)/);
    const txt = (a.getAttribute('aria-label') || a.innerText || '').trim();
    if (m && txt) out.push({name: txt.split('\n')[0], norm: norm(txt.split('\n')[0]), guild: m[1], channel: m[2]});
  });
  return JSON.stringify({channels: out, url: location.href});
})()
"""

MESSAGES_JS = r"""
(() => {
  const msgs = [];
  document.querySelectorAll('[id^="message-content-"]').forEach(el => {
    const content = el.innerText.trim();
    if (!content) return;
    const wrap = el.closest('[class*="message"]');
    const authorEl = wrap ? wrap.querySelector('[class*="username"], [class*="headerText"] h3, [class*="authorInfo"] h3') : null;
    const timeEl = wrap ? wrap.querySelector('time') : null;
    msgs.push({author: authorEl ? authorEl.innerText.trim() : '',
               ts: timeEl ? timeEl.getAttribute('datetime') : '',
               content});
  });
  return JSON.stringify({count: msgs.length, messages: msgs.slice(-80), url: location.href});
})()
"""

# ---------- main ----------
def main():
    tab = find_discord_tab()
    if not tab:
        print("NO DISCORD TAB FOUND"); return
    print("tab:", tab.get("title", "")[:60], "|", tab.get("url", "")[:80])
    ws_url = tab["webSocketDebuggerUrl"]
    ws = WS(ws_url)
    try:
        sidebar = json.loads(evaluate(ws, SIDEBAR_NORM) or "{}")
        chans = sidebar.get("channels", [])
        print("sidebar channels:", len(chans))
        for c in chans:
            print("  -", c["name"][:40], "->", c["norm"][:30])
        results = {}
        for wanted in TARGET_CHANNELS:
            wanted_norm = wanted.replace("-", " ")
            hit = next((c for c in chans if wanted_norm in c["norm"]), None)
            if not hit:
                print(f"channel '{wanted}' NOT in sidebar"); continue
            r = evaluate(ws, CLICK_JS % json.dumps(wanted))
            data = {"count": 0, "messages": []}
            for _try in range(4):
                time.sleep(2 if _try == 0 else 3)
                data = json.loads(evaluate(ws, MESSAGES_JS) or "{}")
                if data.get("count", 0) or _try == 3:
                    break
            print(f"[{wanted}] clicked={r} messages={data.get('count', 0)} url={data.get('url','')[:55]}")
            results[wanted] = data.get("messages", [])
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({"channels": results, "tab_url": tab.get("url", "")}, f, ensure_ascii=False, indent=1)
        print("SAVED:", OUT)
    finally:
        ws.close()

if __name__ == "__main__":
    main()
