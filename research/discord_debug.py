#!/usr/bin/env python3
"""Debug: dump Discord chat DOM structure via CDP (run on Windows)."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_cdp as D

tab = D.find_discord_tab()
if not tab:
    print("NO DISCORD TAB"); sys.exit(1)
ws = D.WS(tab["webSocketDebuggerUrl"])
JS = r"""
(() => {
  const out = {};
  out.articles = document.querySelectorAll('article').length;
  const list = document.querySelector('[data-list-id]');
  out.listId = list ? list.getAttribute('data-list-id') : null;
  out.url = location.href;
  const cands = [];
  document.querySelectorAll('[class*="message"]').forEach(e => { if (e.children.length > 2) cands.push(String(e.className).split(' ')[0]); });
  out.sample = [...new Set(cands)].slice(0, 8);
  out.bodyText = document.body.innerText.slice(0, 400).replace(/\n/g, ' | ');
  out.hasContent = !!document.querySelector('[id^="message-content-"]');
  out.msgAnchors = document.querySelectorAll('a[href*="discord.com/channels"]').length;
  return JSON.stringify(out);
})()
"""
print(D.evaluate(ws, JS)[:1500])
ws.close()
