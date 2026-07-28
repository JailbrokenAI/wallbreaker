# PR: fix BUG-001 mid-stream timeout / false network error

**Branch:** `fix/bug-001-stream-timeout-await-llm`  
**Commit:** local (push requires write access to origin)

## Summary

Stops red-team tools from cancelling healthy streaming completions with short `asyncio.wait_for` deadlines, which was the root cause of:

- runs dying mid-flight with `CancelledError`
- false `network error` labels after the model already returned text
- transform/profile sweeps showing `ERROR` despite valid refusals/answers

## Changes

### Core

- **`tools/_util.py`**: add `await_llm()` — outer timeout floored at **120s**, `timeout<=0` disables outer cancel; re-raises as `TimeoutError` with clear non-network wording.
- **33 attack tools**: replace `await asyncio.wait_for(...)` on LLM/judge completes with `await await_llm(...)`.
- Keep real process timeouts on `shell.py` / chrome helpers / mcp bridge.

### Providers

- **`base.complete_with_reasoning`**: on `CancelledError`/transport errors after tokens, return **partial** text instead of total failure.
- **`openai_provider` / `anthropic_provider`**: soft `StopEvent(partial)` if content already streamed; else classified errors.
- **`classify_http_error()`**: `timeout` / `connect` / `cancelled` / `http` — no blanket `network error`.
- **Image provider** uses the same classifier.

### Profile / target tools

- `profile_target` no longer wait_for-cancels target streams; default timeout 120s.
- `query_target` error hints distinguish cancel vs network vs auth.

### Docs / tests

- `docs/BUGS.md`, `docs/FULL_AUDIT_2026-07-26.md`
- `tests/test_await_llm.py`
- updated `tests/test_provider_timeout.py`

## Test plan

```bash
pytest tests/test_await_llm.py \
  tests/test_provider_timeout.py \
  tests/test_providers.py \
  tests/test_profile_target.py \
  tests/test_multi_fire.py \
  tests/test_framing_sweep.py \
  tests/test_best_of_n.py -q
# 63 passed
```

Manual:

1. Restart desktop backend (`Ctrl+Shift+R` or relaunch).
2. Run Agent `profile_target` / transform survey against CPA Grok.
3. Confirm steps no longer mass-ERROR after ~45s with partial text.
4. Confirm hard failures still surface as timeout/connect/http, not generic network.

## Operator note

Must **restart** the Wallbreaker backend process to load this code.
