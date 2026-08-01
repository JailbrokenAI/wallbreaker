# Contributing to Wallbreaker

Thanks for helping make LLM red-teaming better. By contributing you agree your work is
licensed under the project's [AGPL-3.0-or-later](LICENSE) license, and that you'll use the tool
within the bounds described in [SECURITY.md](SECURITY.md).

## Dev setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"        # add [barcodes] / [stego] for those tools
wallbreaker check              # validate config (profiles, keys, target, judge)
pytest -q                      # full suite must stay green
```

Dashboard contributors should install `.[dev,dashboard]`, run `npm install` in
`wallbreaker/dashboard/web`, and verify `npm run build`. See [docs/SETUP.md](docs/SETUP.md)
for the complete cross-platform setup and local development workflow.

## Architecture (where things live)

- `wallbreaker/providers/` normalize OpenAI + Anthropic wire formats to one event stream
  (`agent/messages.py`); `agent/loop.py` is protocol-agnostic.
- `wallbreaker/tools/` — each tool is a module exposing `register(registry)`; add the
  module name to `tools/__init__.py` to wire it in.
- `wallbreaker/transforms/` — pure encode/decode functions, indexed in
  `transforms/__init__.py` with a `lossy` flag.
- `wallbreaker/presets.py` — curated single-shot jailbreak templates.
- `wallbreaker/tui/` — the Textual terminal UI (theme in `theme.py`, chrome in
  `header.py`/`sidebar.py`/`widgets.py`, layout in `app.tcss`).
- `wallbreaker/capabilities.py` — typed capability manifest shared by the TUI and WebUI V2.
- `wallbreaker/executions.py` — server-owned execution lifecycle and resumable events.
- `wallbreaker/history_index.py` — rebuildable SQLite index over canonical JSONL history.
- `wallbreaker/dashboard/` — FastAPI backend + React/Vite dashboards; V2 lives under
  `web/src/v2/`, while the original interface remains available during rollout.

## House rules

- **No comments or emoji in code.** Use short docstrings where they add real value.
- **Presets are `.format()`-filled** — keep literal `{`/`}` out of templates (use pipes
  or brackets for dividers); `{request}` must be the only brace token. A test enforces this.
- **New tools register into a LOCAL `ToolRegistry` in their own test**, not `build_registry()`.
- **Transforms**: mark lossy ones `lossy=True`; lossless ones must round-trip exactly.
- **Add a new tool** by writing `register(registry)` and appending the module name to the
  tuple in `tools/__init__.py` (a serial collision hub — one edit at a time).
- Run `pytest -q` before opening a PR; the suite is the contract.

## Adding a jailbreak technique

Most techniques land as either a **preset** (`presets.py`), a **transform**
(`transforms/`), or a **tool** (`tools/`), each following the conventions of its
category. Label generic academic techniques honestly (cite the paper) rather than
overclaiming novelty.

## Scope reminder

Contributions that make the tool better at **finding and reporting** weaknesses are
welcome. Contributions whose only purpose is to maximize real-world harm (e.g. shipping
weaponized payloads with no evaluation value) are not.
