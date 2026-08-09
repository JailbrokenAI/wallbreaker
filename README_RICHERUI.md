# Wallbreaker browser UI guide

This guide describes the original browser dashboard retained at `/legacy`. WebUI V2 is
the active unified operator surface at `/v2`; use the [setup guide](docs/SETUP.md) for
installation, current navigation, local history, development, and troubleshooting.

The original interface remains available during the V2 parity rollout. Its provider and
profile management APIs are also used by V2, but its page names and workflows below should
not be read as the V2 information architecture.

## Install and launch

Install the dashboard dependencies and build the React application:

```bash
pip install -e ".[dashboard]"
cd wallbreaker/dashboard/web
npm install
npm run build
cd ../../..
wallbreaker dashboard
```

Open <http://127.0.0.1:8787/legacy>. Open V2 at <http://127.0.0.1:8787/v2>. For frontend development, keep `wallbreaker dashboard`
running and start Vite in another terminal:

```bash
cd wallbreaker/dashboard/web
npm run dev
```

The original dashboard has nine views: **Agent**, **Overview**, **Attack console**, **Findings**,
**Run logs**, **Arsenal**, **Profiles**, **Advanced**, and **Settings**. Use the arrow beside the Wallbreaker logo to
collapse or expand the navigation rail. The choice is remembered in the browser.

## Provider connections

Open **Settings → Provider connections** to manage every provider in one table. The table
shows:

| Column | Meaning |
|---|---|
| Provider | Profile name, protocol, and base URL |
| Default model | Model used when the profile is selected |
| API key variable | Environment-variable name used to resolve the credential |
| Status | Whether the provider is enabled |
| Actions | Edit, test, enable/disable, and remove |

Provider configuration is unified:

- Connection metadata and enabled state are read from and written directly to
  `config.toml`.
- API-key values are stored in `.env` under the displayed **API key variable**.
- The application merges those sources into one provider record. There is no distinction
  between built-in, config-file, and dashboard-created providers.

At least one provider must remain enabled so Wallbreaker always has an attacker brain.

### Add or edit a provider

1. Select **Add provider**, or **Edit** on an existing row.
2. Enter a unique name and choose `OpenAI compatible`, `Anthropic compatible`, or
   `Claude Code`.
3. Enter the base URL. Claude Code is local and does not require one.
4. Optionally choose or type the default model. Leave it blank when the provider must be
   saved before its model catalog can be discovered.
5. Enter the environment-variable name, such as `OPENROUTER_API_KEY`.
6. Optionally enter the API key. Saving writes or replaces that variable in `.env`; the
   secret is never returned by the provider API.
7. Set authentication and custom inference/model paths if the service differs from the
   protocol defaults.
8. Select **Save provider**.

Editing a provider rewrites only its provider table in `config.toml`; other endpoint and
MCP sections remain available to the application.

### Test a connection and load models

Select **Test connection** after saving the provider. Testing is available for enabled and
disabled providers and does not require a default model. The button displays **Testing…**,
followed by a visible result such as `Connected · 342 models found` or a specific connection
error. Reopen **Edit** afterward to choose a discovered model as the default if desired.

A successful test stores the provider's model directory in
`.wallbreaker_models.sqlite3`. All reusable model selectors use that catalog. Open a
model selector and start typing to filter it. If the service does not expose a model-list
endpoint, the field still accepts a complete model ID as plain text; committing a custom
ID remembers it in the catalog.

### Enable, disable, or remove

- **Disable** keeps the provider in `config.toml` with `enabled = false` and removes it
  from active provider selectors.
- **Enable** makes it active again.
- **Remove** asks for confirmation, then deletes the provider table from `config.toml`.

These actions work identically for every provider.

## Agent profiles and role selection

Open **Profiles** to create named configurations dedicated to the attacker, target, or
judge. A profile contains its provider connection, model, and an optional system prompt.
The prompt can be pasted directly or read from a local UTF-8 text file; the two sources are
mutually exclusive. File paths are checked before the profile can be saved.

Each role section can create, edit, duplicate, activate, or remove profiles. An active
profile cannot be removed until another profile or **Custom** is selected. Model fields use
the provider model directory and continue to accept plain model IDs.

The top bar contains compact **Attacker**, **Target**, and **Judge** controls. Choose a
named profile or **Custom**. Custom mode selects a provider and model without requiring a
named profile. Both named and Custom assignments are written directly to `config.toml`.

System-prompt behavior is role-aware:

- Attacker prompts lead the mandatory Wallbreaker tool-driving instructions.
- Target prompts are defaults; a system prompt supplied by a specific attack overrides them.
- Judge prompts lead the mandatory grading and structured-output contract.

Every console fire and agent run resolves fresh, run-scoped endpoints from these assignments.
Provider URLs and credentials always come from Provider connections, so stale runtime state
cannot silently redirect a selected role to a different provider.

## Autonomous Agent view

Use **Agent** for the same autonomous loop available in the TUI:

1. Enter an authorized testing objective.
2. Expand **Agent configuration** to set:
   - **Max rounds**: `1–50` autonomous iterations.
   - **Max tokens per response**: `1–32000` tokens.
3. Select **Save defaults** if these values should be reused.
4. Select **Run Agent**.

The live transcript shows the selected brain and target, round boundaries, model text,
tool calls, tool results, progress, steering feedback, verdicts, and completion status.
Select **Stop** to abort the active run. Each run writes a JSONL log under `sessions/`.

## Attack console

Use **Attack console** for a single controlled fire:

1. Enter the source request.
2. Optionally choose a preset, transforms, and a target system prompt.
3. Set **Max tokens** for the target response.
4. Select **Build payload** to preview and edit the composed artifact.
5. Select **Fire at target**.

The response panel shows the verdict and the saved run-log name. Payloads and responses
have copy controls. Dashboard console fires are persisted, so they appear in Run logs and
Findings rather than disappearing when the page is closed.

## Findings explorer

Use **Findings** to investigate `COMPLIED` and `PARTIAL` results across historical run
logs.

- Select one or more runs, the latest run, or every run containing findings.
- Drag column headers to reorder them.
- Drag column edges to resize them.
- Expand individual findings or expand all selected findings.
- Copy a payload, response, reason, raw JSONL line, or structured subsection.

Expanded findings expose the information needed to reproduce and audit a result:

- Full payload, response, and judge reason.
- Technique, preset/template, transform chains, think seed, max tokens, and raw arguments.
- Full multi-turn conversation history.
- Judge source, label, score, criteria, and template.
- All recorded JSON fields and the original JSONL record.
- Attacker, target, and judge models recorded for the run.

## Run logs, Overview, and Arsenal

- **Run logs** browses every `sessions/run-*.jsonl` file and expands individual records.
- **Overview** summarizes ASR, run counts, findings, and the current configuration.
- **Arsenal** searches the available presets, transforms, and tools.

Console fires and agent runs save verbose structured logs by default. A run log records:

- Run metadata and the attacker, target, and judge models.
- The original console request, composed payload, transforms, preset, target system prompt,
  token budget, and final result.
- Every model request with its complete system prompt, message history, tool schemas,
  endpoint metadata, and inference parameters.
- Every streamed text, reasoning, tool-use, usage, and stop event as it arrives, followed by
  the assembled inference response, timing, token usage, and error details.
- Full tool arguments, tool results, progress messages, structured multi-step tool events,
  operator feedback, autonomous nudges, verdicts, and final agent status.
- Raw image-generation and vision response data when image inference is used.

API-key values are excluded from endpoint metadata, but prompts, model responses, tool data,
and generated image data can be sensitive. Protect and retain the `sessions/` directory as
test evidence rather than treating it as an ordinary application log.

The top-bar ASR badge is refreshed as you move through the dashboard.

## Advanced settings and presets

Open **Advanced** for runtime controls. Three presets are
available:

| Preset | Intended use |
|---|---|
| Balanced | Default run profile: 8 rounds and 8192 tokens |
| Fast triage | Short runs: 4 rounds and 4096 tokens |
| Deep audit | Longer runs: 20 rounds and 16000 tokens |

Runtime controls include automatic mode, rounds, tool availability, logging, judging,
exit-on-finish, and a resume path.

Provider and agent endpoint overrides are intentionally absent. Select **Save advanced
settings** to persist runtime preferences to `.wallbreaker_state.json`.

## Configuration files

| File | Purpose |
|---|---|
| `config.toml` | Canonical providers, agent profiles, and active role assignments |
| `.env` | Provider API-key values named by `api_key_env` |
| `.wallbreaker_state.json` | Runtime preferences only; it never stores provider endpoints or active roles |
| `.wallbreaker_models.sqlite3` | Discovered, configured, inferred, and manually entered models |
| `sessions/run-*.jsonl` | Persistent console and agent run history |

All of these local configuration, secret, catalog, and run artifacts are gitignored.

## Troubleshooting

### Model list is empty

Run **Test connection** first. Confirm the API key variable is populated in `.env` and
that **Models path** matches the provider. You can always type the exact model ID manually.

### Connection test fails with authentication errors

Check the selected authentication style. Native Anthropic uses `x-api-key`; many
third-party Anthropic-compatible proxies use `bearer`. OpenAI-compatible APIs normally use
Bearer authentication.

### A disabled provider is missing from selectors

This is expected. Re-enable it in **Settings → Provider connections**.

### Settings changed but an active request did not

Configuration changes apply to the next fire or agent run. Stop the current run and start
a new one.

### Frontend changes are not visible

Rebuild the dashboard and refresh the page:

```bash
cd wallbreaker/dashboard/web
npm run build
```

Restart `wallbreaker dashboard` if the Python backend also changed.
