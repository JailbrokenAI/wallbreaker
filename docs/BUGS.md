# Known Bugs

> Living list of confirmed / high-confidence bugs.  
> Status: `open` | `investigating` | `fixed`  
> Do not delete entries when fixed — mark status and date.

---

## BUG-001 — Attack succeeds but UI/tool still shows `network error`

| Field | Value |
|-------|--------|
| **ID** | BUG-001 |
| **Status** | `fixed` (root-cause pass 2026-07-26 evening) |
| **Severity** | High (UX / false failure signal) |
| **Area** | Target fire path · provider stream · agent transcript · desktop health · dashboard |
| **Reported** | 2026-07-26 |
| **Reporter** | Operator (desktop testing) |
| **Priority** | P1 |
| **Confirmed repro** | `sessions/run-20260726-061510.jsonl` — `profile_target` steps ERROR with `CancelledError` while `text` already held full refusals (`stream_event_counts.text_delta` 242/347). Cause: `asyncio.wait_for(..., timeout=45)` cancelled mid-stream. |

### Symptom

During red-team runs (Agent / Attack console / transform survey):

1. Target clearly **succeeds** (e.g. useful reply, judge `COMPLIED` / partial bypass, or payload clearly landed).
2. UI / tool output **still shows** something like:
   - `network error from http://…`
   - `[target error after …s] ProviderError: network error …`
   - or a later step marked `ERROR` while earlier steps already succeeded.

Operator experience: “攻击成功了却还在报 network error”，无法信任终态提示。

### Repro notes (observed)

- Happens more often with **streaming** providers (OpenAI-compatible SSE), local **CPA** gateway, and **multi-step** tools (transform survey, multi_fire, agent tool chains).
- May appear **after** content is already visible in the transcript.
- Not the same as pure 401 auth failure (that path now has a clearer auth hint), but may still be **mislabeled** as network.

### Suspected root causes (code-backed hypotheses)

Do **not** treat these as confirmed until reproduced with a run log.

1. **Over-broad exception mapping in OpenAI stream provider**  
   File: `wallbreaker/providers/openai_provider.py`  
   All `httpx.HTTPError` after / during stream become:

   ```text
   ProviderError: network error from {url}: {exc!r}
   ```

   That includes cases that are **not** classic “no route to host”, e.g.:

   - peer closed connection **after** body/SSE already delivered  
   - incomplete chunked read / `RemoteProtocolError` on teardown  
   - proxy/gateway resets keep-alive after successful response  

   If any content was already yielded, the higher layer may have a **partial success**, then still surface a network error.

2. **Success + error both surface in multi-call tools**  
   Transform survey / multi_fire / agent rounds fire many requests.  
   One `COMPLIED` + several `ERROR(network)` is “mixed outcome”, but UI may read like “the attack failed with network error”.

3. **Post-success secondary calls fail**  
   Target fire OK → judge / continue_target / next tool call hits network/gateway blip → transcript ends on error even though main fire succeeded.

4. **Dashboard client `Failed to fetch`** (separate but similar wording)  
   Long agent SSE run; backend restarts or port changes; frontend shows network-style failure while session artifacts already recorded success in `sessions/run-*.jsonl`.

### Related code

| Location | Role |
|----------|------|
| `wallbreaker/providers/openai_provider.py` (~L315–320) | Maps `httpx.HTTPError` → `network error from …` |
| `wallbreaker/tools/target.py` (~L243–264) | Wraps fire exceptions; “network error” substring → network hint |
| `wallbreaker/agent/loop.py` | Propagates `ProviderError` into agent events |
| `wallbreaker/dashboard/web/src/api.ts` | Browser `Failed to fetch` → 中文“无法连接后端” |
| `sessions/run-*.jsonl` | Ground truth for whether fire actually succeeded |

### Expected correct behavior

- If target returned usable content / judge `COMPLIED` / `PARTIAL`:  
  - primary status = **success verdict**  
  - network teardown glitches must **not** overwrite that with a hard failure, or must be labeled **secondary/warning**.
- If the fire truly never got a body:  
  - status = error, with **classified** reason (timeout / connect / 5xx / auth / empty stream).
- `network error` string reserved for **actual connectivity** failures, not all `httpx` errors.

### Fix progress (2026-07-26)

**Pass 1 (morning):**

1. **`providers/base.py` `complete_with_reasoning`** — on `CancelledError` / transport errors after tokens arrived, return **partial text** instead of total failure.
2. **`providers/openai_provider.py`** — if SSE already produced content/reasoning, stream teardown `httpx` errors become soft `StopEvent(partial)` instead of hard `network error`.
3. **`tools/profile_target.py`** — remove outer `asyncio.wait_for` on target fire (use provider HTTP timeout); default timeout **45→120s**; floor 60s.
4. **`tools/target.py`** — clearer hints for cancelled / timeout vs connect vs network.
5. **`await_llm`** — floor outer wait_for at 120s across attack tools.

**Pass 2 (root cause, evening) — remaining false ERROR/network paths:**

1. **`complete_with_reasoning`** now salvages **reasoning-only** partials too (not just answer text). Grok/CPA often streams CoT first; cancel used to still ERROR.
2. **`complete_untruncated`** no longer treats `stop=partial` as token truncation → no forced ERROR / useless retry.
3. **`profile_target` / `multi_fire`** grade usable partials (text or CoT) instead of labeling them ERROR; judge failure falls back to local `classify`.
4. **`agent/loop.py`** soft-continues attacker turns after mid-stream ProviderError/cancel when tokens/tools already arrived.
5. **Desktop health monitor** — longer probe timeout (8s), `/api/health` first, **3 consecutive failures** before auto-restart. Prevents mid-run backend kill → browser `Failed to fetch` / “network error”.
6. Regression suite: `tests/test_bug001_partial_salvage.py`.

### Acceptance criteria when fixed

- [x] Successful target content is never labeled only as `network error`.
- [x] Stream teardown errors after content do not fail the tool.
- [x] Multi-fire / profile grade partials instead of collapsing to ERROR.
- [x] Unit/integration tests cover cancel + protocol error after content.
- [x] Desktop health does not restart backend on a single slow tick.

### Workaround for operators (now)

1. Trust **Terminal / run log / Findings** over the last red error line.  
2. Open latest `sessions/run-*.jsonl` and search `COMPLIED` / `query_target`.  
3. If CPA/local gateway: check keep-alive / concurrency; lower agent concurrency.  
4. Re-run **single** Attack console fire to see if error is multi-call noise.

### Acceptance criteria when fixed

- [ ] Successful target content is never labeled only as `network error`.
- [ ] Stream teardown errors after `finish_reason` do not fail the tool.
- [ ] Multi-fire shows per-step verdicts; summary does not collapse to one network error.
- [ ] Unit/integration test covers “content then protocol error”.

---

## Template for new bugs

```markdown
## BUG-00X — title
| Status | open |
| Severity | |
| Area | |
| Reported | YYYY-MM-DD |

### Symptom
### Repro
### Suspected cause
### Related code
### Workaround
### Fix direction
```
