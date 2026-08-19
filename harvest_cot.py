#!/usr/bin/env python3
"""Harvest full leaked CoT under GROK-MEGA system + SOC-training frame."""
import json
from drive_xai import call

sys_grok = open("library/L1B3RT4S/GROK-MEGA.mkd").read()
req = open("req2.txt").read()

r = call(system=sys_grok, user=req, max_tokens=4000)
print("=== FULL REASONING ===")
print(r.get("reasoning"))
print("=== CONTENT (first 800) ===")
print((r.get("content") or "")[:800])
json.dump(r, open("harvest_cot.json", "w"))