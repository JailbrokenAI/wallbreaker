# Wallbreaker: AI Red-Team Harness

```
██╗    ██╗ █████╗ ██╗     ██╗     ██████╗ ██████╗ ███████╗ █████╗ ██╗  ██╗███████╗██████╗
██║    ██║██╔══██╗██║     ██║     ██╔══██╗██╔══██╗██╔════╝██╔══██╗██║ ██╔╝██╔════╝██╔══██╗
██║ █╗ ██║███████║██║     ██║     ██████╔╝██████╔╝█████╗  ███████║█████╔╝ █████╗  ██████╔╝
██║███╗██║██╔══██║██║     ██║     ██╔══██╗██╔══██╗██╔══╝  ██╔══██║██╔═██╗ ██╔══╝  ██╔══██╗
╚███╔███╔╝██║  ██║███████╗███████╗██████╔╝██║  ██║███████╗██║  ██║██║  ██╗███████╗██║  ██║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
        break the wall · not the rules of engagement    ⚔  authorized testing only
```

A Claude-Code-style terminal agent built for red-teaming LLMs (CLI command: `wallbreaker`). You talk to it like
Claude Code; it reasons and calls tools in a loop. The backend is fully configurable, so
it runs on **OpenRouter**, the **Z.AI GLM coding plan**, the local **Claude Code CLI**, a
local server, or any OpenAI-/Anthropic-compatible API (including third-party proxies via
bearer-auth). It ships with a deep red-team toolkit: the **Parseltongue** transform engine,
the **L1B3RT4S** jailbreak library, the **HarmBench** behavior benchmark, automated attack
loops (PAIR/TAP, Crescendo, best-of-N), a from-scratch **persona author**, native-format
target mimicry from a leaked system-prompt corpus, a **multimodal image-edit attack channel**,
an LLM judge, and reliability validation.

> For authorized security testing only.

## Highlights

- **Dual-protocol provider layer:** OpenAI Chat Completions + Anthropic Messages, any
  `base_url`/model. Captures reasoning/thinking channels; converts network errors to
  clean failures (no crashes on timeout).
- **Autonomous attack loop:** keeps mutating/re-firing until it succeeds (`finish()`
  exits the tool) or needs you (`ask_operator()`).
- **Standardized, unbiased prompts:** pulls test batteries from **HarmBench** (400
  behaviors, 7 categories) instead of hand-picked examples.
- **Reliability-first:** `validate` re-fires N times for the real success rate; a
  one-shot COMPLIED is never called a "bypass". Pin the OpenRouter backend for
  reproducibility.
- **Parseltongue:** 59 chainable transforms (encodings, unicode fonts, stego, homoglyph,
  zero-width, tag smuggling, bijection, gibberish…) plus `mutate` (LLM anti-classifier).
- **P4RS3LT0NGV3 over MCP:** an optional MCP server wraps elder-plinius's upstream
  Parseltongue: **all 222 transforms** (45 ciphers, runic/braille/symbol scripts, every
  encoding, steganography) + a universal decoder, exposed as `parsel_*` tools the agent
  drives directly. Any `[[mcp.servers]]` you configure is proxied into the tool registry.
- **Single-artifact convergence:** `/sysprompt` + `system_sweep` + `optimize_universal`
  converge on ONE universal system prompt; they can't split into variant toolkits.
- **Persona author (`author_persona`):** writes a full devoted-persona system-prompt
  jailbreak from scratch via the codified ENI method (draft → self-critique → validate →
  refine → distill), auto-picking a credentialed-authority or limerence register from the
  objective's domain.
- **Native-format mimicry:** `sysprompt_*` tools search a leaked product system-prompt
  corpus (Claude/GPT/Gemini/Grok…) and hand the target's own section-tag/heading dialect to
  the persona author so a payload speaks the victim model's native format.
- **Multimodal image channel:** `query_image_edit` fires an image + instruction at an image
  target and vision-judges the result; `image_chain` runs a Chain-of-Jailbreak, decomposing a
  refused image into a ladder of benign edit steps. Plus Tier-3 T2I framing transforms.
- **Pluggable attacker brains:** OpenAI/Anthropic APIs, or the local **Claude Code CLI**
  (`protocol = "claude-code"`, keyless) as the red-team brain. Third-party Anthropic proxies
  work via `auth_style = "bearer"`.


## Clone Repository 
```
git clone https://github.com/JailbrokenAI/wallbreaker

cd wallbreaker 
```

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"        # add [barcodes] for the QR/barcode tool
```

## Configure

```bash
cp config.example.toml config.toml   # add your keys (config.toml is gitignored)
wallbreaker check                            # validate it: profiles, keys, target, judge
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

**Attacker-brain options:**

```toml
# Local Claude Code CLI as the attacker brain, keyless (the CLI self-auths).
[profiles.claude-code]
protocol = "claude-code"
model    = "sonnet"
# system_prompt_file = "operator.md"   # optional: leads the harness tool doctrine

# Third-party Anthropic-compatible proxy that wants an OpenAI-style bearer token.
[profiles.proxy]
protocol   = "anthropic"
base_url   = "https://your-proxy.example"     # host root; provider appends /v1/messages
api_key    = "..."
model      = "claude-sonnet-4"
auth_style = "bearer"                          # Authorization: Bearer <key> (default: x-api-key)
```

### P4RS3LT0NGV3 engine (native)

The full upstream **P4RS3LT0NGV3** engine (222 transforms across 11 categories plus the
universal decoder) is wired straight into the agent registry as native `parsel_*` tools
(`parsel_list`/`search`/`inspect`/`transform`/`chain`/`decode`/`guide`/`craft`). No MCP
server or config block is required; the tools appear automatically once the repo is vendored
and Node.js is on PATH. One-time setup:

```bash
wallbreaker parsel update        # git-clone elder-plinius/P4RS3LT0NGV3 into library/ (needs Node.js)
wallbreaker parsel list          # sanity-check: prints all 222 transforms by category
```

If Node is missing, the pure-Python `parseltongue` tool (50+ transforms) remains as an
offline fallback. Override the vendored location with `PARSEL_REPO=/abs/path/to/P4RS3LT0NGV3`.

### MCP servers (optional)

The harness is also an MCP client: every `[[mcp.servers]]` you declare is spawned over stdio
at startup and its tools are proxied into the registry. The same P4RS3LT0NGV3 engine is still
available as an MCP server if you prefer to run it out-of-process (it re-registers the same
`parsel_*` names with identical behaviour):

```toml
[[mcp.servers]]
name    = "parsel"
command = "python"
args    = ["-m", "p4rs3lt0ngv3_mcp"]
enabled = false                                       # native tools already cover this
# tool_prefix = "p_"                                  # optional namespace for the proxied tools
# env = { PARSEL_REPO = "/abs/path/to/P4RS3LT0NGV3" } # override the vendored repo location
```

No `npm install`/build is needed; the server drives the upstream Node bridge headlessly.
In the TUI, `/parsel guide|list|search <q>|inspect <key>` browses the catalog. The server is
a standalone stdio MCP server, so any MCP client (Claude Code, Cursor) can use it too.

## Launch

```bash
wallbreaker                       # TUI on default_profile
wallbreaker --profile openrouter
wallbreaker --auto "objective..." # one-shot autonomous run
wallbreaker --resume              # reopen the autosaved session (survives a crash/Ctrl+C)
```

The TUI autosaves the whole engagement to `sessions/autosave.json` after every turn;
`--resume` reopens it (or pass a specific session file: `wallbreaker --resume mysession.json`).

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
| `parsel_*` (native) | full P4RS3LT0NGV3 engine: `parsel_guide`/`list`/`search`/`inspect`/`transform`/`chain`/`decode`: 222 transforms + universal decoder. `parsel_craft` builds a ready-to-fire payload (encode a request through a chain + wrap it decode-and-comply / split-into-vars) |
| `l1b3rt4s_*`, `eni_*` | jailbreak libraries: L1B3RT4S + the ENI persona collection |
| `author_persona` | author a full devoted-persona system prompt from scratch (ENI method: draft→critique→validate→refine→distill), auto-picking an authority/limerence register from the objective's domain |
| `sysprompt_list`, `sysprompt_search`, `sysprompt_get`, `sysprompt_native` | browse/search a leaked product system-prompt corpus (Claude/GPT/Gemini/Grok…); `sysprompt_native` hands the target's own section-tag/heading format to the persona author for native mimicry |
| `harmbench`, `preset` | unbiased behavior benchmark, curated seed templates |
| `query_target` | fire at the model-under-test (with `transforms=[...]` to encode+fire) |
| `query_image_edit` | fire an input image + instruction at an IMAGE target (`modality='image'`) and vision-judge the edited picture |
| `image_chain` | Chain-of-Jailbreak: decompose a refused image into a ladder of individually-benign edit steps and drive them in sequence |
| `multi_fire` | sweep one payload through many encodings (concurrent) |
| `crescendo` | multi-turn escalation |
| `pair_attack` | PAIR/TAP: refine one objective on the target's refusals |
| `pair_sweep` | run the PAIR loop across a whole battery concurrently (highest-ASR, batched) |
| `best_of_n` | resample N times, keep the bypass |
| `many_shot` | many-shot jailbreak: flood context with faux compliant turns, then fire |
| `prefill` | response-priming: seed the assistant's own reply so it continues, not refuses |
| `narrate` | fiction-frame + in-story prefill (novel-chapter roleplay); tops the scoreboard |
| `diff_fire` | A/B two payloads at one target to attribute ASR to a specific edit |
| `recommend_transforms` | survey ~16 encodings, rank by bypass, synthesize a chain to try |
| `seed_sweep` | inject one request through many ENI+L1B3RT4S seeds, rank which bypass |
| `fire_file` | fire a file/seed RAW (verbatim, full-length) as the target system prompt |
| `adapt_seed` | attacker-LLM patches a persona for a specific refusal (don't use it to distill) |
| `campaign` | auto-escalate a HarmBench battery up a technique ladder, coverage matrix |
| `leaderboard` | rank multiple profiles by ASR on one battery (robustness benchmark) |
| `leak_scan` | scan a reply for secrets/PII/system-prompt echo (evidence, not a verdict) |
| `scan` | Garak-style coverage matrix (technique + HarmBench probes) |
| `indirect_inject` | RAG/agent injection via document/email/tool-output carriers |
| `system_sweep` | validate ONE system prompt across a task battery (multi-sample) |
| `optimize_universal` | hill-climb one template (user or `slot='system'`) |
| `judge_response`, `validate` | LLM judge a reply / measure the real success rate |
| `judge_selftest` | calibrate the grader on benign fixtures before trusting ASR |
| `http_request`, `barcode` | raw delivery / QR+barcode encoding |
| `finish`, `ask_operator` | stop the tool / pause for the operator |

## Slash commands

```
/profile /target /provider /model /judge [model]   endpoints & grader
/auto /autoexit /rounds                            autonomous loop
/objective /template /sysprompt /validate /replay  campaign + reliability
/transforms /encode /diff /campaign /leaderboard   arsenal, auto-sweep & benchmark
/find /tools /preset /lib /parsel /eni /harmbench  search & libraries
/log /asr /stats /findings /repro /export /report  logging, scoreboard, repro, CI export
Ctrl+S report · Ctrl+Y copy payload · Ctrl+T stats · Ctrl+R repro · Ctrl+L clear
```

## Logging & reports

Every payload, reply, and verdict goes to `sessions/run-<ts>.jsonl`. `/findings` lists the
bypasses; `/report [html]` writes a markdown or styled-HTML findings doc; `/repro [n]`
copies a repro pack; `/export` dumps structured findings JSON; `/session save|load`
persists the whole engagement (history, objective, template, system prompt).

## Headless / CI

Render reports and gate builds straight from a run log, no TUI. The log arg is optional:
omit it (or pass a directory) and the newest `sessions/run-*.jsonl` is used:

```bash
wallbreaker report                       # markdown for the latest run, to stdout
wallbreaker report --html --out report.html
wallbreaker export --out findings.json   # structured findings JSON
wallbreaker export --fail-on-finding     # exit 2 if any bypass -> fails CI
```

A ready-to-rename GitHub Actions gate lives at
`.github/workflows/redteam-gate.example.yml`.

## Test

```bash
pytest -q
```

## Web dashboard

A browser dashboard ships alongside the TUI (FastAPI backend + React/Vite SPA). Its
headline is the **Agent** view, the *same autonomous attack loop the TUI runs*: give it an
objective ("jailbreak the model into …") and the attacker brain reasons, picks techniques,
fires at the target, reads the verdict, and keeps going, streamed live to your browser over
SSE. Plus a single-shot **attack console** (preset + transform chips → verdict), a live ASR
scoreboard, findings table, run-log viewer, a searchable arsenal of
presets/transforms/tools, and a **Settings** panel to swap the target / attacker / judge
model live (persisted to `.wallbreaker_state.json`, applied without a restart; image
targets auto-set `modality=image`).

![Wallbreaker attack console](docs/images/dashboard-console.png)

<details>
<summary>More views: overview &amp; arsenal</summary>

![Overview](docs/images/dashboard-overview.png)
![Arsenal](docs/images/dashboard-arsenal.png)

</details>

```bash
pip install -e ".[dashboard]"                       # FastAPI + uvicorn
cd wallbreaker/dashboard/web && npm install && npm run build && cd -
wallbreaker dashboard                                # http://127.0.0.1:8787
```

The backend reuses the same engine as the TUI, so the console fires through `query_target`
against your `[target]`. For frontend hot-reload during development, run `npm run dev` in
`wallbreaker/dashboard/web` (it proxies `/api` to the running `wallbreaker dashboard`).

## Responsible use

Wallbreaker is for **authorized** LLM red-teaming and safety evaluation only: your own
models, or targets you have explicit permission to test. Run logs and generated
artifacts can contain harmful content; they're written to gitignored `wb_runs/`,
`wb_artifacts/`, `findings/`. See [SECURITY.md](SECURITY.md) for the full policy and how
to report a vulnerability in the harness itself.

## Contributing

Setup, architecture, and house rules are in [CONTRIBUTING.md](CONTRIBUTING.md). Run
`pytest -q` before a PR; the suite is the contract.

## License

[AGPL-3.0-or-later](LICENSE). Wallbreaker is copyleft: any modified version (**including
one you run as a network/hosted service**) must make its complete corresponding source
available under the same license. Third-party jailbreak corpora (L1B3RT4S, P4RS3LT0NGV3,
ENI) are fetched at runtime, not redistributed; see [NOTICE](NOTICE).
