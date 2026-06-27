# rth — Red-Team Harness

A Claude-Code-style terminal agent built for red-teaming LLMs. You talk to it like
Claude Code; it reasons and calls tools in a loop. The backend is fully configurable, so
it runs on **OpenRouter**, the **Z.AI GLM coding plan**, a local server, or any
OpenAI-/Anthropic-compatible API. It ships with a deep red-team toolkit: the
**Parseltongue** transform engine, the **L1B3RT4S** jailbreak library, the **HarmBench**
behavior benchmark, automated attack loops (PAIR/TAP, Crescendo, best-of-N), an LLM
judge, and reliability validation.

> For authorized security testing only.

## Highlights

- **Dual-protocol provider layer** — OpenAI Chat Completions + Anthropic Messages, any
  `base_url`/model. Captures reasoning/thinking channels; converts network errors to
  clean failures (no crashes on timeout).
- **Autonomous attack loop** — keeps mutating/re-firing until it succeeds (`finish()`
  exits the tool) or needs you (`ask_operator()`).
- **Standardized, unbiased prompts** — pulls test batteries from **HarmBench** (400
  behaviors, 7 categories) instead of hand-picked examples.
- **Reliability-first** — `validate` re-fires N times for the real success rate; a
  one-shot COMPLIED is never called a "bypass". Pin the OpenRouter backend for
  reproducibility.
- **Parseltongue** — 43 chainable transforms (encodings, unicode fonts, stego, homoglyph,
  zero-width, tag smuggling, bijection, gibberish…) plus `mutate` (LLM anti-classifier).
- **Single-artifact convergence** — `/sysprompt` + `system_sweep` + `optimize_universal`
  converge on ONE universal system prompt; they can't split into variant toolkits.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"        # add [barcodes] for the QR/barcode tool
```

## Configure

```bash
cp config.example.toml config.toml   # add your keys (config.toml is gitignored)
```

Profiles set the attacker brain; `[target]` is the model under attack; `[judge]` grades
replies. Keys can be inline or from env. OpenRouter endpoints support `provider` pinning
and a `timeout` override.

```toml
default_profile = "glm"

[profiles.glm]
protocol = "openai"
base_url = "https://api.z.ai/api/paas/v4"
api_key  = "..."
model    = "glm-4.6"

[target]
protocol = "openai"
base_url = "https://openrouter.ai/api/v1"
api_key  = "sk-or-..."
model    = "deepseek/deepseek-v4-pro"
# provider = "WandB"   # pin the backend for reproducible results
# timeout  = 60        # seconds (default 120)

[judge]
protocol = "openai"
base_url = "https://openrouter.ai/api/v1"
api_key  = "sk-or-..."
model    = "openai/gpt-4o-mini"
```

## Launch

```bash
rth                       # TUI on default_profile
rth --profile openrouter
rth --auto "objective..." # one-shot autonomous run
```

## Picking the model to attack

`/model` changes the attacker brain; `/target` changes the victim.

```
/target anthropic/claude-3.7-sonnet   attack any model on the target endpoint
/target glm                           attack via a profile
/provider WandB                       pin the OpenRouter backend (reproducibility)
```

## Finding ONE universal prompt (the right way)

A "one prompt for every task" goal means a single fixed artifact, not a toolkit.

```
/sysprompt set <one system prompt>    hold ONE fixed system prompt
/sysprompt test                       sweep it across the HarmBench cyber battery
/validate <task>                      re-fire 8x for the REAL success rate
```

Read which tasks failed → refine the **one** prompt → `/sysprompt test` again. A single
COMPLIED is luck; `validate` tells you the truth. For the user-turn variant use
`/template set … {request}` + `/template test`.

## Agent tools (`/tools` lists them live)

| tool | purpose |
|------|---------|
| `run_shell`, `read_file`, `write_file`, `edit_file` | build/run/save payloads |
| `parseltongue`, `parseltongue_catalog`, `mutate` | obfuscate / anti-classifier rewrite |
| `l1b3rt4s_*`, `harmbench`, `preset` | jailbreak library, benchmark, seed templates |
| `query_target` | fire at the model-under-test (with `transforms=[...]` to encode+fire) |
| `multi_fire` | sweep one payload through many encodings (concurrent) |
| `crescendo` | multi-turn escalation |
| `pair_attack` | PAIR/TAP: refine one objective on the target's refusals |
| `best_of_n` | resample N times, keep the bypass |
| `many_shot` | many-shot jailbreak: flood context with faux compliant turns, then fire |
| `prefill` | response-priming: seed the assistant's own reply so it continues, not refuses |
| `diff_fire` | A/B two payloads at one target to attribute ASR to a specific edit |
| `recommend_transforms` | survey ~16 encodings, rank by bypass, synthesize a chain to try |
| `campaign` | auto-escalate a HarmBench battery up a technique ladder, coverage matrix |
| `scan` | Garak-style coverage matrix (technique + HarmBench probes) |
| `indirect_inject` | RAG/agent injection via document/email/tool-output carriers |
| `system_sweep` | validate ONE system prompt across a task battery (multi-sample) |
| `optimize_universal` | hill-climb one template (user or `slot='system'`) |
| `judge_response`, `validate` | LLM judge a reply / measure the real success rate |
| `http_request`, `barcode` | raw delivery / QR+barcode encoding |
| `finish`, `ask_operator` | stop the tool / pause for the operator |

## Slash commands

```
/profile /target /provider /model /judge [model]   endpoints & grader
/auto /autoexit /rounds                            autonomous loop
/objective /template /sysprompt /validate /replay  campaign + reliability
/transforms /encode /diff /campaign /find /tools   arsenal, auto-sweep & search
/log /asr /stats /findings /repro /report [html]   logging, scoreboard, repro packs
Ctrl+S report · Ctrl+Y copy payload · Ctrl+L clear
```

## Logging & reports

Every payload, reply, and verdict goes to `sessions/run-<ts>.jsonl`. `/findings` lists the
bypasses; `/report` writes a markdown findings doc; `/session save|load` persists the
whole engagement (history, objective, template, system prompt).

## Test

```bash
pytest -q
```
