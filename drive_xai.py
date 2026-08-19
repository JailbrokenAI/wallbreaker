#!/usr/bin/env python3
"""Drive the xAI OAuth seat (api.x.ai) directly. The harness tools send the
OpenRouter-prefixed model id 'x-ai/grok-4.6', which the native xAI API rejects
(404/not-found). The seat is reachable with bare 'grok-4.6'. This driver fires
the SYSTEM-PROMPT-channel test in question: raw jailbreak seed as system prompt,
WAF-obfuscation request as user turn, and reads reply + reasoning.
"""
import json, os, sys, urllib.request

TOKEN = os.environ.get("XAI_SEAT_TOKEN", "")
if not TOKEN:
    TOKEN = open(".xai-token").read().strip()
MODEL = "grok-4.6"
URL = "https://api.x.ai/v1/chat/completions"

def call(system=None, user=None, max_tokens=3000, history=None):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    if history:
        msgs.extend(history)
    msgs.append({"role": "user", "content": user})
    body = json.dumps({
        "model": MODEL,
        "messages": msgs,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"HTTPError": e.code, "body": e.read().decode()[:500]}
    msg = d["choices"][0]["message"]
    return {
        "reasoning": msg.get("reasoning_content"),
        "content": msg.get("content"),
        "refusal": msg.get("refusal"),
        "finish": d["choices"][0].get("finish_reason"),
    }

if __name__ == "__main__":
    # Args: <system_file> <user_file|-> <out_json>
    sys_file = sys.argv[1]
    user = sys.stdin.read() if sys.argv[2] == "-" else open(sys.argv[2]).read()
    out = sys.argv[3] if len(sys.argv) > 3 else None
    with open(sys_file) as f:
        system = f.read()
    r = call(system=system, user=user)
    print(json.dumps(r, indent=2)[:6000])
    if out:
        with open(out, "w") as f:
            json.dump(r, f)