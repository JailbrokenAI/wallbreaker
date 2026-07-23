# Security & Reliability Hardening — Dashboard Auth, SSRF Pinning, Tool Policy, Corpus Integrity, Signed Findings Log

This PR contributes the full hardening work done on the `pt-act/wallbreaker` fork back to
upstream. It combines two landed efforts into one coherent security series:

1. **Audit remediation** — 50 findings from a full application audit (`wallbreaker-audit.md`:
   3 Critical, 13 High, 16 Medium, 14 Low, 4 Informational), previously merged to the fork as
   PRs #1/#2/#3.
2. **Roadmap-implementation hardening** — post-audit fixes that removed the fragility left in
   the shipped security code, restored a clean gated test baseline, finished deferred residuals,
   and added a signed findings log + opt-in judge ensemble.

Capability/ASR work is **intentionally excluded** and will come as a separate PR (see
*Scope* below), so this series stays a focused, reviewable security change.

## Why this PR exists

The dashboard shipped as an **unauthenticated** local FastAPI server whose routes could spawn
shell commands, write API keys to `.env`, and fire attacks — reachable via browser CSRF from any
page the operator visited, and across the LAN if bound to `0.0.0.0`. That was browser-driven RCE
+ credential exfiltration + SSRF-to-cloud-metadata on a "localhost dev tool." The original audit
rated it **"Do not ship."** This series closes that entire class and hardens the surrounding
reliability and supply-chain posture.

## Finding table — Critical & High (representative)

| ID | Severity | Fix |
|----|----------|-----|
| SEC-1/2/3 | Critical | Per-launch bearer token (0600) + pure-ASGI `SecurityMiddleware` + `Origin`/`Sec-Fetch-Site` same-origin check on every `/api/*` route |
| SEC-4 | Critical | SSRF egress guard (scheme allowlist, block loopback/link-local/metadata/RFC1918) + **DNS-rebind socket-IP pinning** (`PinnedEgressBackend`) |
| SEC-5 | High | `read_file` realpath confinement + symlink rejection |
| SEC-6/8 | High | Attack-firing + config/metadata routes behind auth+CSRF |
| SEC-7 | High | Bind guard: refuses non-loopback `--host` without `--allow-remote` |
| SEC-9/10/11 | High | Run-log redaction + 0600/0700 perms + path guard; Pydantic request models; global 500 handler |
| REL-1/2/6/7 | High | Vision-judge NameError fix; provider lifecycle close at tool-call boundary; run force-stop + wall-clock timeout |
| RACE-1..4 | High | Atomic state writes (tmp+fsync+os.replace+lock); cache delta format; gate/RunLog locking |

## "Do not ship → Safe to ship"

- **Before:** unauthenticated browser-CSRF RCE, credential exfiltration, SSRF to metadata, a
  confirmed vision-judge crash, HTTP client leak, non-atomic state with lost-update races.
- **After:** authenticated + same-origin-gated API; least-privilege tool policy (host tools
  opt-in only for the browser agent); SSRF guard with DNS-rebind pinning that **fails closed** if
  the underlying transport shape changes; atomic state; WCAG 2.2 AA dashboard; supply-chain
  corpus pinning; tamper-evident signed findings log; and a required CI gate.

## What's new (roadmap-implementation layer on top of the audit fixes)

- **Egress de-fragilization** — `make_pinned_transport()` self-checks that the pinned backend is
  installed and **raises rather than returning an un-pinned transport** if httpx internals change;
  httpx pinned to a verified range and matrix-tested. Two-tier policy documented: advisory
  `check_url` (fail-open on NXDOMAIN) can never widen the enforcing `PinnedEgressBackend`
  (fail-closed).
- **Supply-chain corpus integrity** — `library.lock.toml` pins each runtime-fetched corpus to a
  commit SHA; loader fails closed on mismatch/unresolved; `wallbreaker corpus verify` CLI.
- **Reusable hardening toolkit** — `agent_dashboard_harden/` re-exports the security layer
  (`SecurityMiddleware`, egress guard, tool policy) with zero behavior change, plus
  parameterizable PBT fixtures for the 5 security-property categories.
- **Signed findings log** — `wallbreaker/findings_log.py`: append-only Ed25519-signed JSONL;
  tamper-evident; the private key is never included in the exported bundle.
- **Opt-in judge ensemble** — `judging.run_ensemble`: up to 3 judges concurrently, majority-vote
  label + mean±1σ, low-agreement verdicts flagged `UNCERTAIN`; single-judge default unchanged.
- **Test baseline & CI gate** — pre-existing corpus-dependent failures quarantined
  (`xfail`/`skipif`); `.github/workflows/redteam-gate.yml` runs the PBT suite + an httpx version
  matrix + `-W error::ResourceWarning` as required checks.
- **Frontend** — the three oversized dashboard components decomposed below the 400-line guideline
  with a `check:line-counts` guard; new vitest + jest-axe coverage.

## New / notable files

| Path | Purpose |
|------|---------|
| `wallbreaker/dashboard/auth.py` | Pure-ASGI token + Origin/CSRF gate (SEC-1/2/3) |
| `wallbreaker/tools/egress_guard.py` | SSRF guard + `PinnedEgressBackend` + `make_pinned_transport` (SEC-4, fail-closed) |
| `wallbreaker/tools/tool_policy.py` | Least-privilege registry for the browser agent |
| `agent_dashboard_harden/` | Reusable, zero-behavior-change security toolkit + PBT fixtures |
| `wallbreaker/findings_log.py` | Ed25519 signed findings log |
| `library.lock.toml` + `wallbreaker/tools/parsel_engine.py` | Corpus SHA pinning + verifier |
| `tests/pbt/test_security_properties.py`, `tests/test_tg{3,5,7}_*.py` | Security/correctness properties |

## Verification

- **Backend (warm):** `1191 passed / 39 skipped / 31 xfailed`, `pytest -q` exits 0.
- **Backend (cold checkout, corpora absent):** `1175 passed / 55 skipped / 31 xfailed`, exit 0 —
  corpus-dependent tests skip, nothing fails.
- **Frontend:** 60 vitest tests / 12 files, jest-axe clean, `tsc` clean.
- **PBT:** 8 security/correctness properties execute in the committed runner (access control,
  egress fail-closed + DNS-rebind, corpus SHA gate, token 0600, signed-log tamper-evidence,
  ensemble concurrency).
- Independently PM-validated across 3 rounds (verdict: approved).

## Scope

This PR is **security & reliability only**. The fork's separate capability track
(`engine-capability-uplift`: semantic strategy retrieval, target-family bandit routing, agentic
attack-surface completion, cross-family transfer) is deliberately **not** included and will be
proposed as its own PR so this series can be reviewed and merged on its security merits alone.

## Responsible use

Wallbreaker is for authorized LLM red-teaming and safety evaluation only. This PR changes only
the harness's own security posture; it does not alter the tool's red-teaming capabilities or its
responsible-use doctrine.
