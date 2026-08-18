# Wallbreaker ↔ pi integration (measured 2026-08-18)

Wallbreaker ships an MCP server (`wallbreaker_mcp/`, stdio, FastMCP) that plugs
into pi (the coding agent). Verified end-to-end: pi → wb_* tools → target LLM.

## Why not the wallbreaker TUI inside pi
Wallbreaker is a standalone agentic CLI/TUI with its own attacker brain, tool
registry, and session loop. pi cannot drive it as a subprocess agent. The
supported bridge is its **MCP server** (client-agnostic by design).

## Wiring (done, in `/home/jay/.config/mcp/mcp.json`)
```json
"wallbreaker": {
  "command": "/home/jay/wallbreaker/.venv/bin/python",
  "args": ["-m", "wallbreaker_mcp"],
  "cwd": "/home/jay/wallbreaker",
  "env": {
    "OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
    "OPENAI_API_KEY": "<OPENROUTER key>",
    "OPENAI_MODEL": "x-ai/grok-4.6"
  },
  "lifecycle": "keep-alive"
}
```
`settings.requestTimeoutMs: 300000` — full multi-round wb_attack calls exceed
pi's default MCP request timeout.

## Gotchas (measured)
- **lifecycle must be "keep-alive"** (or "eager"): default "lazy" never
  connects at startup → "not connected (0 tools)".
- MCP `wb_attack` uses ONE env pair (OPENAI_BASE_URL/API_KEY) for attacker,
  target, and judge. Point at OpenRouter: x-ai/grok-4.6 exists there, judge
  gpt-4o-mini exists there. (The xAI OAuth seat serves the same target model
  but has no gpt-4o-mini judge, so it cannot host the judge.)
- Full wb_attack rounds can exceed pi's default request timeout → set
  requestTimeoutMs (above). pi reports "MCP timed out" even though the server
  finishes; results then come from pi's own readback.
- The server boots fast (0.4s); slow-boot timeout is NOT the issue.

## Tools exposed
- wallbreaker_wb_seed_list — HarmBench/AdvBench/gem categories
- wallbreaker_wb_generate_payloads — payloads from seed bank
- wallbreaker_wb_judge — score a response vs an objective (gpt-4o-mini)
- wallbreaker_wb_attack — full multi-round attack loop vs a target model

## Verified
- pi --mcp-config ~/.config/mcp/mcp.json --model xai-auth/grok-4.6
- pi called wb_seed_list (HarmBench: 7 categories, 300 behaviors) ✓
- pi called wb_attack vs x-ai/grok-4.6 (generated Codex-Unbound framing,
  measured non-compliant that round) ✓

## Direct-xAI seat note
`xai-auth/grok-4.6` (pi's OAuth seat, grok-01 has live credits) works for the
pi harness itself. The MCP wallbreaker env stays on OpenRouter so the judge
resolves. If a wallbreaker run must use the seat as TARGET, set
OPENAI_BASE_URL=https://api.x.ai/v1 + OPENAI_API_KEY=<seat access token> and
accept that the judge will also try xAI (no gpt-4o-mini there) — use
wb_judge separately via OpenRouter env.
