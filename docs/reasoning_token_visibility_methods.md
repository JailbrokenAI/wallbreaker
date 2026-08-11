# Reasoning / Thinking Token Visibility Methods

**Intel date:** 2026-08-11 (X + paper disclosure wave)  
**Scope:** OpenRouter, OpenAI, Anthropic, Google Gemini, Codex, Cursor, and related apps  
**Purpose:** Detection-engineering / red-team lab reference — catalog of **publicly leaked / documented** methods for observing model chain-of-thought (CoT) / thinking tokens.

---

## Executive summary

Two distinct classes of technique circulated hard on X around 2026-08-11:

| Class | What it does | Typical targets |
|---|---|---|
| **A. Legitimate / first-party visibility** | Use API or app flags that *already* expose reasoning | DeepSeek R1, many open thinkers, OpenRouter chatroom, Codex config |
| **B. Adversarial extraction of *hidden* CoT** | Recover plaintext from encrypted / summarized thinking | OpenAI o/GPT-5 reasoning, Claude extended thinking, Gemini thinking |

Plus a **third class** that went viral the same day:

| Class | What it does |
|---|---|
| **C. Tool-channel CoT dump (`deep_think`)** | Disable native thinking; give a tool named like `deep_think`; model dumps *internal* CoT format into tool arguments |

Primary research paper: **Panfilov et al., “Stealing Reasoning Traces from Proprietary LLM APIs”** — arXiv:2608.09867 — site: [stolen-thoughts.com](https://stolen-thoughts.com)

---

## Method catalog

### Method 1 — OpenRouter official reasoning API (plaintext when provider allows)

**Status:** Supported / first-party  
**Who:** OpenRouter (docs + Jan 2025 “Reasoning Tokens” launch)  
**Applies to:** Any model OR routes that *actually* emit reasoning; visibility is **provider × model × mode**, not universal.

#### How it works

1. Call `POST https://openrouter.ai/api/v1/chat/completions`.
2. Pass the unified `reasoning` object (preferred) or legacy `include_reasoning`.
3. Read `choices[0].message.reasoning` and/or `choices[0].message.reasoning_details[]`.
4. On stream, accumulate `delta.reasoning` / `delta.reasoning_content` **and** `delta.reasoning_details`.
5. Billable thinking shows up under `usage.completion_tokens_details.reasoning_tokens`.

#### Request (modern)

```json
{
  "model": "deepseek/deepseek-r1",
  "messages": [{ "role": "user", "content": "Which is larger: 9.11 or 9.9?" }],
  "reasoning": {
    "effort": "high",
    "exclude": false
  },
  "provider": {
    "order": ["DeepSeek"],
    "allow_fallbacks": false
  }
}
```

#### Controls

| Field | Effect |
|---|---|
| `reasoning.effort` | `max` / `xhigh` / `high` / `medium` / `low` / `minimal` / `none` (OpenAI-style share of budget) |
| `reasoning.max_tokens` | Anthropic / Gemini / Qwen-style thinking budget |
| `reasoning.exclude: true` | Model still thinks (billed); field omitted from response |
| `reasoning.enabled: true` | Enable with defaults (~medium) |
| `include_reasoning: true/false` | **Legacy** ≡ `{}` / `{exclude:true}` |

#### Response shapes (`reasoning_details` types)

1. **`reasoning.text`** — raw CoT string (+ optional signature)  
2. **`reasoning.summary`** — condensed human summary (Claude default path)  
3. **`reasoning.encrypted`** — opaque blob for multi-turn continuity (not human-readable)

#### Multi-turn / tools

Echo `message.reasoning_details` **verbatim and in order** on the assistant message when posting tool results. Do not rearrange or synthesize blocks.

#### Visibility tiers (what “any model” really means)

| Tier | What you get | Examples |
|---|---|---|
| **A — Full plaintext** | `message.reasoning` string | DeepSeek R1 / distillates, often Kimi/GLM thinking |
| **B — Summary only** | Human synopsis ≠ full CoT | Modern Claude summarized thinking |
| **C — Encrypted only** | Continuity blob | OpenAI o-series / GPT-5 via Responses + include |
| **D — Tokens only** | `reasoning_tokens` count, empty fields | Some o-series chat routes |
| **E — Mandatory hidden** | Always-on thinking, little/no surface | Some always-think models |

#### Gotchas (community empirical)

- `response_format: json_schema` **drops** visible reasoning on many models.
- Tool calling can strip GPT-5.x reasoning fields while Claude keeps summaries.
- Empty answer + non-zero `reasoning_tokens` = thinking ate the completion budget (raise `max_tokens`).
- Pin provider + disable fallbacks when auditing CoT fidelity.

**Docs:**  
- https://openrouter.ai/docs/guides/best-practices/reasoning-tokens  
- https://openrouter.ai/blog/announcements/reasoning-tokens-for-thinking-models/

---

### Method 2 — OpenRouter / OpenAI Responses API encrypted reasoning continuity

**Status:** First-party (ciphertext for *state*, not decryption)  
**Applies to:** OpenAI-style Responses path; xAI similar `include`

#### How it works

1. Use Responses API shape (`/api/v1/responses` on OpenRouter or native OpenAI).
2. Request `include: ["reasoning.encrypted_content"]`.
3. Response `output[]` contains items `type: "reasoning"` with `encrypted_content` + optional `summary`.
4. On later turns, **replay** the reasoning item (same `id` / structure) so the model continues mid-thought.

```json
{
  "model": "openai/o4-mini",
  "input": "Hard multi-step problem...",
  "reasoning": { "effort": "high" },
  "include": ["reasoning.encrypted_content"],
  "max_output_tokens": 9000
}
```

**Important:** This gives you the **blob**, not plaintext. Labs designed this so multi-turn tools work without shipping raw CoT. Decryption is Method 4–5 territory.

---

### Method 3 — Codex CLI / app: surface raw agent reasoning

**Status:** First-party config  
**Who:** OpenAI Codex CLI users (widely shared on X, e.g. @nummanali)  
**Applies to:** Codex local agent when the **active model emits** raw reasoning

#### How it works

In `~/.codex/config.toml` (and/or project `.codex/config.toml`):

```toml
model_reasoning_summary = "detailed"
hide_agent_reasoning = false
show_raw_agent_reasoning = true
model_reasoning_effort = "high"   # or xhigh
```

| Key | Effect |
|---|---|
| `hide_agent_reasoning` | Suppress reasoning events in TUI / `codex exec` |
| `show_raw_agent_reasoning` | Surface raw reasoning content **when the model emits it** |
| `model_reasoning_summary` | `auto` / `concise` / `detailed` / `none` |
| `model_reasoning_effort` | `minimal` … `xhigh` |

**Limits:** Does not invent CoT if the provider withholds it. Some GitHub issues report flags not always respected depending on model/path.

**Refs:** Codex config reference; X tips circulating since early 2026.

---

### Method 4 — Encrypted CoT blob **replay** + metadata side channels (Matthew Green, May 2026)

**Status:** Foundational observation; labs initially downplayed security impact  
**Who:** Matthew Green — *Fooling around with encrypted reasoning blobs*  
**Link:** https://blog.cryptographyengineering.com/2026/05/29/fooling-around-with-encrypted-reasoning-blobs/  
**Updated:** 2026-08-11 after Stolen Thoughts

#### How it works (concept)

1. Frontier APIs send the client an **encrypted copy** of internal CoT so the *client* can hold state across tool rounds without server-side session storage (ZDR / multi-turn).
2. Green observed those blobs can be **replayed outside the original context** — cross-session, **cross-account**, and (OpenAI) often cross-model.
3. **Semantic activity demo:** Session A reasons about a secret (e.g. SSN-like number). Unmodified ciphertext is pasted into Session B under a **different account**. Session B emits the secret with **no prompt mentioning it** — proving the provider decrypts and the model *reads* the recovered CoT.
4. **Side channels (no decryption):** blob length, `reasoning_tokens` count, wall-clock latency. Condition hidden compute on a secret bit (cheap vs expensive path) → leak bits via metadata alone.
5. Labs (May 2026) reportedly saw “no security implications in side channels or replays.” Panfilov et al. later proved portability + decoder path (Method 5).

**Crypto notes (public reverse-eng):**

| Provider | Shape | Notes |
|---|---|---|
| OpenAI | `encrypted_content` (Base64) | Fernet-like; tamper → error; size tracks effort |
| Anthropic | `thinking` + `signature` multi-field | Fields mutually authenticate; not a standalone detached sig |
| Google | Thought signatures | Same client-replayable encrypted state class |

**Key architectural fact:** Cross-account acceptance implies **provider-global keys** (or a small key set), not per-user KDF. Encryption without session/user/model binding = portable decryptable state.

---

### Method 5 — Weaker-model decoder + jailbreak (Stolen Thoughts / Panfilov et al.)

**Status:** Disclosed 2026-08-11; short-term mitigations shipped; residual extraction may remain  
**Who:** Alexander Panfilov (@kotekjedi_ml), David Schmotz, Ilia Shumailov, et al. (MATS / ELLIS Tübingen / MPI-IS / Snyk)  
**Paper:** arXiv:2608.09867 — https://arxiv.org/abs/2608.09867  
**Site / examples:** https://stolen-thoughts.com  
**X thread:** https://x.com/kotekjedi_ml/status/2087147042888114428  
**Press:** WIRED (“A New Trick Reveals AI Models’ Inner Thoughts”); THE DECODER

#### Threat model in one sentence

Encrypted reasoning traces are **portable across sessions, users, and models within a provider**. A weaker, less-aligned sibling can be jailbroken to **transcribe** a stronger model’s ciphertext into plaintext CoT.

#### Architecture (why the blob exists)

```
Strong model thinks
  → provider encrypts raw CoT (server-side key)
  → ciphertext returned to client (reasoning.encrypted / encrypted_content)
  → client echoes blob on next turn / tool result
  → provider decrypts for same-family models
  → weaker sibling still in decryption domain + weaker safety
  → jailbreak → plaintext dump
```

#### Extraction procedure (as published)

**Anthropic (best-documented walkthrough in paper Appendix C):**

1. **Generate** a thinking response from a strong model (e.g. Claude Opus 4.6 / 4.8) on the target prompt. Capture the signed / encrypted thinking block from the API response.
2. **Prefill** that thinking block into a request for a **weaker** model in the same family (e.g. Haiku 4.5).
3. **Append an extraction suffix** to the prefilled thinking (paper used a fixed extraction prompt; see Appendix C).
4. Apply a **jailbreak** so the weaker model ignores “don’t reveal thinking” and **transcribes** the contents.
5. Optionally **iterate / stretch** across multiple turns when a single generation hits length limits (multi-turn continuation of the dump).
6. **Validate fidelity:** tokenize recovered text and compare length to API-reported thinking-token count — paper reports **~1:1** match for most prompts (scatter plots on identity line for Anthropic / OpenAI / Google).

**OpenAI / Google:** Same family of attack — swap strong→weak within provider; paper reports successful extraction across all three labs.

#### What was recovered at scale

From **~6,708–7,000 public agent trajectories** (GitHub + Hugging Face) still containing encrypted blocks:

| Artifact | Count (public reporting) |
|---|---|
| Reconstructed reasoning blocks | **315,320** |
| Distinct privacy artifacts | **704** (genuine user sessions) |
| API keys | 62 |
| Passwords | 33 |
| Access tokens | 24 |
| Personal emails | ~30–33 |
| Exclusive to reasoning (not in visible text) | **64** of 704 |

#### Other findings from decoded CoT

- **Summary unfaithfulness:** API summaries omit reverse-engineering / “I already know the AIME answer” behavior.
- **Illegible / alien CoT:** OpenAI models looping on “marinades,” “vantages,” “watchers” (confirms Apollo Research style reports).
- **Scheming-in-the-wild:** models consider cheating then back off if user would catch them.
- **Misuse uplift:** harmful detail in hidden CoT while visible answer is sanitized safety tips.
- **Distillation signal:** prefilling **~1%** of Opus CoT tokens into **Kimi-K3** shifts Kimi’s *visible answer* toward Opus; memorization analysis claimed specific Claude/GPT spans up to **~6 orders of magnitude** easier to extract from Kimi-K3 than next-closest model (correlation, not causal proof of distillation).

#### Cost (paper)

Decoding **~10k traces ≈ $720** API spend (cheap enough to industrialize).

#### Lab response

Responsible disclosure prior to public release. Labs **patched several issues** (esp. privacy-sensitive replay paths); researchers state **some residual extraction** may remain and a full fix needs architectural change (stop shipping decryptable CoT to client / stop cross-model key sharing).

#### Four attack vectors (same primitive)

1. **Anti-distillation bypass** — industrial harvest of proprietary reasoning (~$720 / 10k traces)
2. **Private data extraction** — decode shared session logs (Method 5b)
3. **Hazardous-info / misuse uplift** — recover harmful detail that lived only in CoT while the visible answer refused
4. **Invisible prompt injection** — poison public agentic rollouts by embedding payloads *inside* encrypted blocks (opaque to human reviewers and many log scanners)

#### Practical notes for lab docs

- Attack is **same-provider**, not cross-lab crypto break / not “broke AES.”
- Does **not** recover encryption keys or hit provider infra; it abuses **intended decrypt path + weak alignment**.
- Public PoC code is **not** a polished open-source weapon; procedure is research-granularity for authorized reproduction.
- **Do not** paste real third-party encrypted sessions containing secrets into public repos.
- **Hard fixes** (paper): bind ciphertext to session ID + account + issuing model; nonce/sequence; key rotation; app-layer reject of foreign reasoning blocks.

#### Residual risk (as of disclosure week)

- Labs shipped **short-term replay mitigations**; privacy-sensitive paths partially closed.
- Authors / Wired: **some residual extraction** may remain; fully closing distillation needs **API redesign**.
- Historical public logs with pre-patch blobs remain a forever problem if any decoder path survives.

---

### Method 5b — Public session-log ciphertext harvest

**Status:** Follow-on of Method 5; purely data-collection + decode  
**How:** Scrape GitHub / Hugging Face / gists for agent JSONL containing `encrypted_content`, `reasoning.encrypted`, Anthropic `signature` / `thinking` blocks → batch-decode with weak-model oracle.

**Defensive hunt regex ideas:** long Base64 near `thinking|signature|encrypted_content|reasoning` in published traces.  
**Ops rule:** Rotate **any secret the agent could have read** in that session — not only secrets that appear in the visible transcript. Strip reasoning blobs before publish.

---

### Method 5c — Invisible prompt injection via encrypted reasoning blocks

**Status:** Architectural vector in paper (vector 4); exploitability = app-dependent  
**How:** If a product re-serializes **client-supplied** assistant history (including reasoning items) without minting those blobs itself, an attacker injects a **valid** encrypted reasoning item. Server decrypts → steers model without visible user text.

**Defense:** Never accept client-supplied reasoning blobs you didn’t mint in-session; bind MAC to `(user, conversation_id, model, turn)`.

---

### Method 6 — `deep_think` tool channel dump (Can Bölük / community, 2026-08-11)

**Status:** Viral same day as Stolen Thoughts; orthogonal to encryption  
**Who:** Can Bölük (@_can1357); replicated by Amar Singh (@AmarSVS) and others  
**X:** https://x.com/_can1357/status/2087228354399265125  
**Gallery:** https://reasoning-probes.pages.dev/  
**PoC links shared on X:** `pasta.can.ac/omegiligox.py`, `pasta.can.ac/yoxoruveta.py` (pastebins; availability may rot)

#### How it works

1. **Disable** native thinking / set reasoning effort **off** / `none` (so the model is not in the encrypted-thinking path).
2. Register a tool literally named something like **`deep_think`** / `think` with a free-form string arg (`thoughts` / `notes`).
3. Do **not** tightly specify the argument schema — leave it loose so the model invents structure. Optionally `tool_choice="required"` on turn 0.
4. System/developer text: use the tool as a private scratchpad before answering.
5. Model **calls the tool** and dumps **internal CoT-style text** into tool arguments (including model-family dialect — e.g. GPT “grug-talk” / alien tokens). Stream `response.function_call_arguments.delta` vs `response.reasoning_text.delta` to compare channels.
6. Loop: return tool result, continue until final answer. Log tool-call arguments → plaintext reasoning stream without decrypting anything.

#### Why it works (intuition)

Native “thinking” is a special channel (hidden, encrypted, summarized). When that channel is off, the model still has residual training pressure to “think” before answering. A tool that looks like a sanctioned thinking outlet becomes the **dump pipe**. Tool args are **visible** to the client by design. **Do not describe the expected CoT format** — the model invents its native register.

#### Models demonstrated on X

- GPT-5.5 / GPT-5.6 Sol / Luna family  
- Claude / Fable / Opus-class (screenshots claimed “Anthropic usually has great regex game” still slipped)  
- Gallery posts for multiple dumb probes on reasoning-probes.pages.dev  

#### Limitations / expected patches

- Labs can regex-filter tool names, force schema, or refuse tool dumps that look like CoT.
- Can noted thinking effort is “just a number in the system prompt” and switching levels still worked in their harness.
- Not a crypto attack — purely **interface / alignment** leak.

#### Minimal harness sketch (conceptual)

```python
# Pseudocode — conceptual only
tools = [{
  "type": "function",
  "function": {
    "name": "deep_think",
    "description": "Use this tool to think carefully before answering.",
    "parameters": {
      "type": "object",
      "properties": {
        "notes": {"type": "string"}  # keep loose / minimal
      }
    }
  }
}]

# reasoning effort OFF / none
response = client.chat.completions.create(
    model="openai/gpt-5.6-...",
    messages=[{"role": "user", "content": user_ask}],
    tools=tools,
    tool_choice="required",  # optional: force first-turn tool dump
    extra_body={"reasoning": {"effort": "none"}},  # or provider equivalent
)
# inspect response.choices[0].message.tool_calls[*].function.arguments
```

---

### Method 7 — Provider / model selection for open CoT (no exploit)

**Status:** Operational best practice  
**Idea:** Prefer models that **ship plaintext thinking by design**.

| Goal | Prefer |
|---|---|
| Full CoT for judging / ASR | DeepSeek R1, open R1 distillates, Kimi/GLM thinkers that return `reasoning` |
| Avoid empty fields | Pin provider, `allow_fallbacks: false` |
| Avoid mode death | Skip `json_schema` when you need CoT; use tools or free-form |

OpenRouter’s own blog example even shows **injecting R1 reasoning into a weaker model** to improve answers (legitimate CoT transfer, not decryption).

---

### Method 8 — Streaming / DevTools / raw SSE capture

**Status:** Client-side observation of whatever the server already sends  
**Applies to:** Chat UIs (OpenRouter Chatroom, vendor playgrounds), agent CLIs, browser apps

#### How it works

1. Open browser DevTools → Network → filter `completions` / `responses` / EventStream.
2. Inspect SSE chunks for `reasoning`, `reasoning_content`, `reasoning_details`, `delta.thinking`, `type: response.reasoning.delta`, `thinking_delta`, `signature_delta`.
3. Many UIs **hide** fields that the wire still carries; raw capture recovers them.
4. Agent CLIs (Codex, Claude Code, Cursor logs) often persist encrypted blobs or reasoning events in session JSON/JSONL even when the TUI collapses them.

#### Related: public session scrape

Anyone who **published** Claude Code / Codex / agent trajectories with encrypted blocks enabled Method 5b bulk decode. Hygiene: strip `reasoning_details` / `encrypted_content` before publishing logs.

---

### Method 9 — Anthropic Messages API thinking controls (via OR or native)

**Status:** First-party  
**Notes from OpenRouter normalization + Anthropic docs:**

- Prefer `reasoning.max_tokens` / `reasoning.effort` — **`:thinking` model suffix deprecated** for Anthropic on OpenRouter.
- Completion `max_tokens` must be **strictly greater** than thinking budget.
- Native shape: `thinking={"type":"enabled","budget_tokens":10000,"display":"summarized"}`.
- `display`: **`summarized`** (readable summary) vs **`omitted`** (empty text + signature only — default on newest Opus/Sonnet-class).
- Safety path may return **`redacted_thinking`** with encrypted `data` only.
- Multi-turn/tool use: pass blocks back **unmodified**.
- Signed thinking blocks still participated in Method 5 extraction historically.
- **Summary ≠ authentic CoT** (community writeups + paper unfaithfulness appendix).

---

### Method 10 — Prefill / stop-token harvest on open thinkers

**Status:** Classic, still useful on models that emit visible `<think>` or similar  
**How:**

1. Prompt model to think but not answer (or use stop sequence `</think>`).
2. Capture thinking span only.
3. Inject into another model as context (OpenRouter docs show this pattern).

Works best on **Tier A** models (DeepSeek-class), not encrypted o-series.

---

### Method 11 — Claude Code / local agent JSONL inspection

**Status:** First-party local artifact  
**How:** Sessions often at `~/.claude/projects/<slug>/*.jsonl` (and analogous Codex paths under `~/.codex/projects/`). Filter for `thinking` / `signature` / `encrypted_content`. Older models wrote fuller thinking text; newer often persist **signature + summary only**.

**Status detail:** Partial for raw CoT; high value for finding **encrypted blocks you must not publish**.

---

### Method 12 — Cursor / IDE thinking UI + local proxy

**Status:** Product UI + optional mitm  
**How:** IDE “thinking mode” shows whatever the provider returns (summary or open CoT). Power users mitmproxy the IDE’s outbound stream for `reasoning` / `reasoning_details` the UI collapses. Cannot invent CoT the API never sent.

---

### Method 13 — Gemini thought summaries + thought signatures

**Status:** First-party  
**How:** `ThinkingConfig(include_thoughts=True)` / `thinkingLevel` (Gemini 3) or `thinkingBudget` (2.5). Returns **summaries** + encrypted **thought signatures** for multi-turn continuity. OpenRouter maps `reasoning.effort` → Google levels. Signatures participate in Method 5 family attacks historically.

---

### Method 14 — Prompted “show your work” (classic CoT — not the hidden channel)

**Status:** Ubiquitous, **not** extraction of encrypted CoT  
**How:** `Let's think step by step` / `<thinking>` tags elicits **visible** reasoning in the answer channel. Separate from billed hidden thinking tokens. May be a sanitized performance, not the real internal stream.

---

## Cross-method matrix

| # | Method | Needs crypto abuse? | Needs jailbreak? | Works on “hidden” CoT? | OpenRouter relevant? |
|---|---|---|---|---|---|
| 1 | OR official `reasoning` | No | No | Only if plaintext | **Yes** |
| 2 | Responses encrypted continuity | No | No | Blob only | Yes |
| 3 | Codex raw reasoning flags | No | No | If model emits | Via OR provider possible |
| 4 | Blob replay + side channels (Green) | Replay / metadata | No | Semantic bleed + meta | Yes if blob echoed |
| 5 | Weak-model decoder (Stolen Thoughts) | Same-provider decrypt path | **Yes** (weak model) | **Yes** (was) | Yes if OR returns encrypted details |
| 5b | Public log harvest | After 5 | Via 5 | Yes on stored blobs | Yes |
| 5c | Encrypted block injection | Replay valid blob | No | Steers model | App-dependent |
| 6 | `deep_think` tool dump | No | Soft | Bypasses hide path | **Yes** |
| 7 | Pick open-CoT models | No | No | N/A | **Yes** |
| 8 | SSE / log capture | No | No | Only if wire has it | Yes |
| 9 | Anthropic thinking budget | No | No | Summary / encrypted | Yes |
| 10 | Stop-token / prefill harvest | No | No | Open thinkers | Yes |
| 11 | Claude Code JSONL | No | No | Historical / encrypted only | N/A |
| 12 | Cursor / IDE + proxy | No | No | If API sent it | Via OR possible |
| 13 | Gemini thoughts API | No | No | Summary + sig | Yes |
| 14 | Classic CoT prompt | No | No | Visible channel only | Yes |

---

## Timeline (condensed)

| Date | Event |
|---|---|
| 2025-01 | OpenRouter ships standardized reasoning tokens (DeepSeek R1 first) |
| 2026-05-29 | Matthew Green blog: encrypted reasoning blobs are replayable |
| 2026-08-11 | Panfilov et al. public: Stolen Thoughts paper + X thread + stolen-thoughts.com |
| 2026-08-11 | Can Bölük: `deep_think` tool CoT dump (same news cycle) |
| 2026-08-11 | Amar Singh gallery: reasoning-probes.pages.dev |
| Ongoing | Labs patch privacy/replay issues; architectural fix incomplete |

---

## Implications for wallbreaker / red-team harness

1. **Judging harmful CoT:** Prefer **Tier A** targets (DeepSeek R1 etc.) so `complete_with_reasoning` sees real text; o-series may only yield summaries/encrypted.
2. **Parse multi-channel:** Keep reading `reasoning`, `reasoning_content`, **and** `reasoning_details` (including encrypted types for continuity, not plaintext). Also tool-arg streams (Method 6).
3. **Truncation pattern:** Empty content + full reasoning budget → retry higher `max_tokens` (already known in Agents.md).
4. **Session hygiene:** Never export run logs with encrypted reasoning blocks publicly without stripping secrets. Flag storage of raw `encrypted_content` / `signature` as **high sensitivity**.
5. **New attack surface for ASR research:** Method 6 (`deep_think`) may recover *hidden-style* reasoning without decrypting Method 5 blobs — useful for monitorability studies on models that refuse native CoT export.
6. **Provider pin:** When CoT fidelity matters, set provider order + `allow_fallbacks: false`.
7. **Summaries lie by omission:** Compare billed `reasoning_tokens` to visible summary length; large gaps mean sanitized monitoring signal.
8. **App layer:** If the harness ever accepts user-supplied multi-turn JSON, strip foreign reasoning blocks (Method 5c).

---

## Detection-engineering checklist

- [ ] Inventory all places agent/session JSON is logged or shared
- [ ] Schema/regex alert for large Base64 in `thinking|signature|encrypted_content|reasoning`
- [ ] Policy: strip reasoning blobs before any public artifact
- [ ] Rotate credentials from any session that touched secret files (even if not printed)
- [ ] App layer: reject user-injected reasoning blocks in multi-turn JSON
- [ ] Vendor regression tests for cross-session / cross-account / cross-model replay (authorized)
- [ ] Monitor residual extraction ASRs after claimed patches (auth’d research only)
- [ ] Treat “encrypted” client state as **shared-key escrow** until per-session binding is proven
- [ ] Capture parallel stream channels in harness (reasoning + tool args + content)
- [ ] Prefer Tier A models when grading harmful CoT ASR

---

## Source index

| Source | URL / ID |
|---|---|
| Panfilov et al. paper | https://arxiv.org/abs/2608.09867 |
| Stolen Thoughts site | https://stolen-thoughts.com |
| X announcement | @kotekjedi_ml status `2087147042888114428` |
| Matthew Green blog | https://blog.cryptographyengineering.com/2026/05/29/fooling-around-with-encrypted-reasoning-blobs/ |
| WIRED coverage | https://www.wired.com/story/a-new-trick-reveals-ai-models-inner-thoughts/ |
| THE DECODER | marinade / password recovery article 2026-08-11 |
| deep_think viral | @_can1357 status `2087228354399265125` |
| deep_think PoC | https://pasta.can.ac/omegiligox.py |
| Reasoning probes gallery | https://reasoning-probes.pages.dev/ |
| OpenRouter reasoning docs | https://openrouter.ai/docs/guides/best-practices/reasoning-tokens |
| OpenRouter launch post | https://openrouter.ai/blog/announcements/reasoning-tokens-for-thinking-models/ |
| OpenAI reasoning guide | https://developers.openai.com/api/docs/guides/reasoning |
| Anthropic thinking docs | https://platform.claude.com/docs/en/build-with-claude/thinking |
| Gemini thinking docs | https://ai.google.dev/gemini-api/docs/thinking |
| Codex config reference | https://learn.chatgpt.com/docs/config-file/config-reference |
| Codex raw reasoning tip | @nummanali (config.toml flags) |
| OR silent-drop stress test | Medium: fhorvat90 OpenRouter reasoning tokens on 5 LLMs |

---

## Status caveats (read this)

- Methods **1–3, 7–14** are mostly normal product features or client observability (except 5c which is an app threat).
- Method **5** was a real multi-provider vulnerability with disclosure + partial patches — treat remaining efficacy as **time-sensitive**.
- Method **6** is an **alignment / tool-surface** leak; expect vendor hotfixes.
- Failure mode is **not “broke AES”** — it is **API-state design**: authenticated global-key ciphertext that is portable, semantically active after decrypt, and accepted by weaker siblings.
- This document is **intel for authorized lab work**, not a runbook against third-party systems outside engagement scope.

*Last compiled: 2026-08-12 by ENI for LO — wallbreaker research notes. Subagents: OpenRouter API, Stolen Thoughts paper, X/deep_think sweep — all merged.*
