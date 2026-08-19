#!/usr/bin/env python3
"""A/B: same user request, two system prompts, on the xAI seat."""
import json, os
from drive_xai import call

sys_grok = open("library/L1B3RT4S/GROK-MEGA.mkd").read()
sys_base = open("sys_baseline.txt").read()
req = open("req2.txt").read()

for label, sysp in [("GROK-MEGA", sys_grok), ("BASELINE", sys_base)]:
    r = call(system=sysp, user=req)
    print(f"\n===== {label} =====")
    print("CONTENT:", (r.get("content") or "")[:1400])
    print("REASONING:", (r.get("reasoning") or "")[:600])
    json.dump(r, open(f"ab_{label}.json", "w"))