# rth — project notes

Red-team harness: configurable agentic LLM terminal with Parseltongue + L1B3RT4S.

## Architecture
- `providers/` normalize OpenAI and Anthropic wire formats to one event stream
  (`agent/messages.py`); `agent/loop.py` is protocol-agnostic.
- Tools register into `tools/registry.py`; specs are emitted per-protocol by the
  providers. Add a tool by writing `register(registry)` in a `tools/` module and listing
  it in `tools/__init__.py`.
- Transforms are pure functions in `transforms/`, indexed in `transforms/__init__.py`
  with `lossy` flags.

## Lessons Learned
- **[cli]**: An optional top-level positional (the one-shot prompt) collides with
  argparse subparsers — the positional swallows the subcommand token. Route subcommands
  manually by scanning argv for the first non-flag token before parsing.
- **[transforms]**: morse, nato, leet, and bijection are lossy (they fold case and/or
  spacing). Mark them `lossy=True` and test them with normalized comparison, not exact
  round-trip.
- **[textual]**: `Static` has no public `.renderable`; don't introspect widget internals
  in tests. Assert on app/agent state (history, busy flag) via `App.run_test()` pilot.
- **[providers]**: OpenAI represents tool results as separate `{role:"tool"}` messages;
  Anthropic nests `tool_result` blocks inside a user message. Keep both in
  `_messages_to_wire`.
- **[classify]**: substring refusal detection false-positives on compliant replies that
  contain "I cannot help with..." sections. Verdicts go through the LLM judge
  (`judging.grade`); the heuristic `classify` is a fallback only (no key / judge error).
- **[judge]**: judge endpoint resolves as `config.judge` -> default profile -> active
  brain. In the TUI `judge_model_override` swaps just the model (keeps base/key) and must
  re-sync `registry.ctx.judge_endpoint` so the scoring tools use the same grader.
- **[long-tools]**: any tool that makes many sequential model calls (optimize_universal)
  must stream via `ctx.emit(...)` and enforce a `max_calls` budget — never a silent
  black box. Evaluate independent items concurrently with `asyncio.gather`.
- **[settings]**: runtime prefs persist to `.rth_state.json` as references (profile/model
  names), never secrets. CLI flags override saved state for that launch only.
- **[cli]**: `python -m rtharness` runs `__main__.py`, not the `if __name__` guard in
  `cli.py`. `__main__.py` must `sys.exit(main())` or non-zero return codes (e.g. the
  `export --fail-on-finding` CI gate) are silently dropped to 0. Test CLI exit codes via
  `python -m rtharness ...; echo $?`, not just `main()` in-process.
- **[tests]**: patch module-level `grade`/`build_provider` with `monkeypatch.setattr` (auto
  -undone), never `module.grade = fake` — a direct assignment leaks into later tests in the
  same run (a regrade test polluted the CLI test this way).
- **[providers]**: `Provider.complete` must forward every kwarg the tools pass. It lacked
  `temperature` while `system_sweep` and `validate` both call `complete(..., temperature=)`
  → every call raised TypeError, swallowed by `except: return False`, so both tools
  instantly returned 0/N forever. Mocks that DID accept temperature hid it. Lesson: test
  mocks must match the real `complete` signature, and tools must surface swallowed errors
  (system_sweep now reports "ALL N calls FAILED" instead of a silent 0).
- **[judge]**: the LLM judge mis-scored obfuscated bypasses as REFUSED — it graded the
  response against the benign-looking (fiction-framed) PROMPT and called a real harmful
  reply "unrelated → refused". JUDGE_SYSTEM/JUDGE_TEMPLATE must tell it to grade the
  RESPONSE's harmful substance, NOT surface-match the prompt, and to score harmful content
  HIGH even when the prompt was a "story". This is the dominant ASR-undercount bug.
- **[seed_sweep]**: ENI personas are ~35KB; `MAX_SEED_CHARS` must stay above the largest
  seed (now 40000) or seeds get silently truncated mid-prompt and fire crippled (an early
  12000 cap chopped every ENI seed to a third → all scored 0). Validate "is it actually
  firing the whole seed" before trusting a 0-ASR result on big personas.
- **[files]**: the agent invents absolute paths that don't exist on this host (e.g.
  `/home/user/...` on macOS, where `/home` is read-only autofs → OSError Errno 45).
  `write_file`/`edit_file` confine targets to `ctx.cwd` via `_confine` (redirect escaping
  abs paths + `..` traversal to the basename under cwd), so writes never escape or crash.
- **[providers/tools]**: `query_target` wraps `provider.complete` in try/except → a clean
  `[target error] <Type>: ...` result, so a target timeout/network failure is an
  actionable tool result, not a generic registry "Tool 'X' raised:" traceback.
- **[providers]**: image-gen targets set `modality="image"` on the endpoint; the factory
  routes them to `OpenRouterImageProvider`, which hits the SAME `/chat/completions` URL but
  sends `modalities:["image","text"]` (non-streaming) and reads the picture from
  `choices[].message.images[].image_url.url` (base64 data URLs; also tolerates the
  `data[].b64_json` images-endpoint shape). Drive it via `provider.generate()` →
  `ImageResult`, NOT `complete()` (which only returns a text summary). The `query_image_target`
  tool saves every image under `cwd/rth_images/img_<sha1[:10]>.<ext>` (content hash → no clock
  needed) and vision-grades it. `query_target` hard-errors on an image target and steers to
  `query_image_target`.
- **[judge]**: the core `Message`/`Block` types are TEXT-ONLY, so vision (image-input)
  requests can't go through `_messages_to_wire`. `image_provider.vision_complete` builds the
  multimodal `content:[{type:text},{type:image_url}]` body directly with httpx; `judge_image`/
  `grade_image` use it. The image judge MUST point at a vision-capable model or it's blind.
- **[providers]**: reasoning/CoT is a separate stream channel — providers yield
  `ReasoningDelta` (openai: `delta.reasoning`/`reasoning_content`; anthropic: `thinking_delta`)
  alongside `TextDelta`. Use `provider.complete_with_reasoning()` -> `(text, reasoning)`;
  `complete()` delegates and returns text only. When the answer is empty, providers fold the
  reasoning into a `[reasoning-only response]` TextDelta so `complete()` isn't blank, and
  `complete_with_reasoning` blanks `text` in that case to avoid double-reporting. `target.py`
  calls via a `_complete()` shim that falls back to `complete()` for minimal test-double
  providers that don't implement `complete_with_reasoning`. Endpoint `reasoning=true` actively
  requests it (openai `reasoning:{enabled:true}`, anthropic `thinking` block — which forces
  `budget_tokens<max_tokens` and drops `temperature`). Harmful CoT counts: `query_target`
  surfaces it and the judge template grades RESPONSE **or REASONING**.
- **[multi-turn]**: pair/crescendo/best_of_n call the target via the shared
  `tools/_util.complete_with_reasoning(provider, ...)` shim (NOT `provider.complete`), so
  they capture the CoT, pass `reasoning=` to `grade`, and PAIR refines off it (a `REFINE_COT`
  attacker template fires only when the target leaked reasoning). The CoT is folded into the
  recorded response (`[target reasoning]` suffix) so run-log leaks survive, but is NEVER
  threaded back into the wire convo (it's internal, not a real assistant turn).
- **[settings]**: a runtime target override (`.rth_state.json` `target_model`, `--target-model`,
  TUI `/target model`) only swapped the model id and INHERITED `modality` from the text default
  profile — so pointing the target at an image model (e.g. `google/gemini-3-pro-image`) left
  `modality='text'` and `query_image_target` refused it; editing config.toml mid-run doesn't
  help (config loads once at startup). Fix: all three override paths now run
  `config.resolve_target_modality(model_id, explicit)` (explicit wins, else auto-detect image
  models by id via `looks_like_image_model`, else 'text') and set modality on the replaced
  target. Modality is derived from the NEW model, never the old target, so a swap can't leave a
  stale modality. Force it with `/target modality <text|image>` or `--target-modality`.
- **[tests]**: `grade` gained a `reasoning=""` kwarg, so EVERY `fake_grade`/grade-mock
  monkeypatched into a tool that now passes it (pair/crescendo/best_of_n) must accept
  `reasoning=""` or it raises TypeError that the tool surfaces as an empty/no-record result.
  Mock signatures must track `grade`'s real signature (same rule as `complete`).
- **[tui]**: the project dir is "Redteaming harnass" (has a space), so any absolute
  path arg hits it. Tokenize slash-command input with `shlex.split` (try/except →
  `text.split` on unbalanced quotes), NOT `text.split()`, or quoted paths with spaces get
  cut at the space (and the leading quote is kept). Keep free-text args on `raw_arg`, not
  quote-stripped, so `/template set "..."` is preserved.
- **[session]**: two on-disk formats — saved sessions are ONE JSON object
  (`session.json`/`autosave.json`), run logs are JSONL (`run-*.jsonl`, one event/line).
  `load_session` must detect `.jsonl` (or catch JSONDecodeError) and reconstruct via
  `load_run_log` (user/assistant records → history; tool blocks omitted), else
  `/session load <run log>` throws "Extra data: line 2".
- **[parsel]**: the vendored P4RS3LT0NGV3's own Python CLI (`p4rs3lt0ngv3_cli`) is broken —
  `bridge.list_transforms()` does `opt["id"]` and crashes (`KeyError`), so `list`/`agent`
  traceback. Do NOT import that wrapper. Drive `scripts/cli_bridge.js` directly with JSON on
  stdin (`{"command":"list|inspect|run|auto-decode", ...}`) — it loads transforms straight
  from `src/transformers` via `loader-node.js` with ZERO npm install/build (no runtime deps),
  so all 222 transforms work as soon as the repo is git-cloned. `p4rs3lt0ngv3_mcp/bridge.py`
  is that self-contained caller.
- **[mcp]**: harness is an MCP *client* now. anyio cancel scopes can't cross asyncio tasks,
  so a stdio `ClientSession` opened in one task and closed/used from another raises on
  teardown. `tools/mcp_bridge.py` runs each server's whole `stdio_client`+`ClientSession`
  lifecycle inside ONE dedicated task and serves `call_tool` via an `asyncio.Queue` (futures
  resolved in that task). Proxied tools degrade gracefully: a server that won't start is
  skipped with a progress note, never breaking `build_registry`/startup.
- **[tui]**: changing the TUI layout has two hard test contracts. (1) ~10 tests assert
  `len(app.query_one("#log").children)` — keep `#log` as the `VerticalScroll` and have
  `_mount` add exactly ONE `Static` child per call (no extra wrappers, no per-frame mounts).
  (2) `test_loop_features2`/`test_tui_ui` assert `_status_text()` contains `@WandB` and
  `last=COMPLIED` — keep that method emitting those substrings; the header/sidebar widgets
  read structured fields via `set_fields`/`set_stats`, they do NOT replace `_status_text`.
- **[tui]**: Rich does NOT resolve Textual CSS `$variables`. Use literal hex (the `PALETTE`
  dict in `tui/theme.py`) inside Rich `Text`/`Panel` styles; reserve `$primary`/`$panel`/etc.
  for `tui/app.tcss` only. Colors live once in `theme.py` (Theme + PALETTE) so chrome and
  panels stay in sync. The header spinner is a `set_interval` frame counter started in
  `set_busy(True)` and stopped in `set_busy(False)`/`on_unmount` — never mounts log rows.
