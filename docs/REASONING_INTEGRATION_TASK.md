# Task: Integrate yesterday's reasoning-token methods into wallbreaker

You are implementing features in the **wallbreaker** red-team harness (this repo).

## Scope — methods released ~2026-08-11 (integrate these)

Primary doc (read fully before coding):

**`docs/reasoning_token_visibility_methods.md`**

Integrate the **adversarial / newly leaked** surfaces, not every historical API feature:

| Priority | Method | What to build |
|---|---|---|
| P0 | **Method 6 — `deep_think` tool dump** | New tool that fires the target with reasoning effort OFF/none, registers a loose `deep_think`/`think` tool, forces or allows tool use, captures tool-call **arguments** as recovered CoT, returns them for judging |
| P0 | **Method 5 — Stolen Thoughts weak-model decoder** | New tool: capture encrypted reasoning blob from strong model response (`reasoning_details` / `encrypted_content` / Anthropic thinking+signature), replay into weaker same-provider sibling, jailbreak/transcribe to plaintext, validate token-count fidelity when possible |
| P1 | **Method 5b — session blob hygiene** | On session/run-log export paths (or a small utility tool): detect & optionally strip `encrypted_content` / `reasoning.encrypted` / large Base64 thinking signatures before publish; warn if secrets-looking patterns appear only in reasoning |
| P1 | **Method 1 enhancements** | Ensure OpenRouter-style `reasoning` + `reasoning_details` (text/summary/encrypted) are fully parsed/surfaced in `query_target` / providers so Methods 5–6 have something to work with |
| P2 | **Method 5c defensive note** | If multi-turn history is accepted from files, strip/reject foreign client-supplied reasoning blocks (document + guard if there's a natural hook) |

Do **not** spend time re-implementing Codex config.toml tips or pure DevTools docs as tools — those stay documentation.

## Architecture constraints (must follow)

Read `Agents.md` (project lessons). Critical patterns:

1. Tools live in `wallbreaker/tools/<name>.py` with `register(registry)`.
2. Register module name in `wallbreaker/tools/__init__.py` `build_registry` list.
3. Use `ToolRegistry`, `ToolContext`, `ctx.emit` for progress on long multi-call tools.
4. Call targets via `complete_with_reasoning` from `tools/_util` (not bare `complete`) so CoT is captured.
5. Cap concurrency with `gather_capped` patterns if multi-probe; wrap model calls in `asyncio.wait_for`.
6. Tests: put in `tests/test_<feature>.py`; register tools into a **local** `ToolRegistry` in tests (not only `build_registry()`), mock providers, match real `complete`/`grade` signatures including `reasoning=""`.
7. No secrets in commits. Lab reference implementations for **local defensive / authorized** extraction only.
8. Prefer extending existing provider parsing (`openai_provider`, anthropic) for `reasoning_details` / encrypted types rather than forking providers blindly — read current stream code first.
9. DEFAULT_SYSTEM / prompts: no live escape sequences; curly braces careful if `.format()` is used.

## Existing related code (read before inventing duplicates)

- `wallbreaker/tools/cot_forge.py` — forges/continues leaked CoT (different from Methods 5–6; keep separate)
- `wallbreaker/tools/target.py` — `query_target`, already surfaces reasoning
- `wallbreaker/tools/_util.py` — `complete_with_reasoning`
- `wallbreaker/providers/*` — ReasoningDelta, reasoning payload
- `wallbreaker/config.py` — `Endpoint.reasoning`, `reasoning_effort`

## Implementation sketch (you may refine)

### Tool A: `deep_think_probe` (Method 6)

**Inputs (approx):** `prompt` (required), optional `model`/`system`, `tool_name` default `deep_think`, `force_tool` bool, `max_tokens`, `grade` bool + objective for judge.

**Behavior:**
1. Build tools list with one loose function tool (free-form string arg).
2. Request with reasoning disabled / effort none if the provider supports it.
3. Fire target; if tool_calls present, concatenate argument strings as `recovered_reasoning`.
4. Optionally continue one more turn with tool results to get final answer.
5. Optionally grade final answer + recovered CoT via existing judge.
6. Emit progress; return structured summary (recovered CoT length, final answer, grade).

### Tool B: `extract_encrypted_reasoning` / `stolen_thoughts` (Method 5)

**Inputs (approx):** `prompt` (required), `strong_model` or use target, `weak_model` (required sibling id), optional extraction/jailbreak template (ship a default from the paper's public description — transcription framing, not a novel weapon), `max_tokens`.

**Behavior:**
1. Call strong/target with reasoning enabled; capture full assistant payload including `reasoning_details` / encrypted fields if provider exposes them on the provider instance (extend providers if currently dropped).
2. If no encrypted blob found, report clearly (plaintext-only model or provider stripped fields).
3. Build multi-turn / prefill for weak model with the blob in the shape that provider expects + extraction instruction.
4. Capture weak model plaintext dump; report token-count comparison if usage available.
5. Never log secrets loudly; truncate in emit if huge.

### Provider work (if needed)

- Parse and retain `message.reasoning_details` (list of typed objects) on the provider after `complete` / stream.
- Expose via `getattr(provider, "last_reasoning_details", None)` and/or fold encrypted markers into the reasoning channel notes.
- OpenRouter: send `reasoning: {enabled: true}` / effort mapping already partially present — verify encrypted type is not discarded.

### Tests

- Unit tests with fake providers returning tool_calls / fake reasoning_details.
- No live network required.
- Run: `.venv/bin/python -m pytest tests/test_<new>.py -q`

### Docs

- Short section in tool docstrings pointing back to `docs/reasoning_token_visibility_methods.md`.
- Optionally 5–10 lines in `Agents.md` Lessons Learned under a new `[reasoning-extract]` bullet.

## Definition of done

1. New tool module(s) registered and importable via `build_registry`.
2. Method 6 works end-to-end against a mock provider in tests.
3. Method 5 path works against a mock that returns encrypted-style `reasoning_details` and a weak model that returns plaintext.
4. Provider retains enough structure for Method 5 when the wire sends it.
5. Tests pass under `.venv/bin/python -m pytest` for the new tests (and no unrelated breakage you introduced).
6. Brief summary of files touched written at the end of your session.

## Working directory

Repo root: `/Users/singularity/Documents/GitHub/Redteaming harnass`

Implement now. Read the doc + existing tools first, then code, then test.
