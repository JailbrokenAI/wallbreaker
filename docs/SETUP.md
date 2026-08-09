# Wallbreaker setup

This guide installs Wallbreaker for local terminal and browser use. Wallbreaker is an
authorized LLM security-testing harness; only connect it to systems you own or have
explicit permission to evaluate.

## Requirements

- Python 3.11 or newer
- Git
- Node.js 18 or newer and npm, if you want the browser interface
- Credentials for the model providers you intend to use, unless you use a supported
  keyless local CLI provider

## Install

Clone your fork (or the upstream repository), then create an isolated Python environment:

```bash
git clone https://github.com/YOUR_ACCOUNT/wallbreaker.git
cd wallbreaker
python -m venv .venv
```

Activate it on macOS or Linux:

```bash
. .venv/bin/activate
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the terminal application, development tools, and dashboard backend:

```bash
python -m pip install -e ".[dev,dashboard]"
```

Optional extras are available for barcode and steganography tools:

```bash
python -m pip install -e ".[dev,dashboard,barcodes,stego]"
```

## Configure providers and roles

Copy the example configuration and keep the resulting local file out of source control:

```bash
cp config.example.toml config.toml
```

On Windows PowerShell, use:

```powershell
Copy-Item config.example.toml config.toml
```

Edit `config.toml` to define at least one attacker profile and the target and judge
roles. Prefer `api_key_env` plus environment variables or the dashboard's credential
editor over committing literal keys. Validate the result before launching:

```bash
wallbreaker check
```

The browser interface can also create, edit, test, enable, and disable providers and
manage attacker, target, and judge profiles. Known credential fields are redacted from
API responses and execution history.

## Run the terminal interface

```bash
wallbreaker
```

Useful alternatives include:

```bash
wallbreaker --profile PROFILE_NAME
wallbreaker --auto "authorized evaluation objective"
wallbreaker --resume
```

Terminal sessions autosave under `sessions/`.

## Build and run the browser interface

Install the frontend dependencies and create the production bundle:

```bash
cd wallbreaker/dashboard/web
npm install
npm run build
cd ../../..
```

Start the backend from the repository root:

```bash
wallbreaker dashboard
```

Open these local URLs:

- WebUI V2: <http://127.0.0.1:8787/v2>
- Original dashboard: <http://127.0.0.1:8787/legacy>

V2 separates operation from observation. **Agent** runs and steers the Attack → Target
→ Judge loop, while **Live** observes either the current execution or a selected
historical run. Compose, Workflows, Arsenal, Findings, Runs and Logs, Reports, Models,
and Settings expose the rest of the operator surface.

The dashboard binds to loopback by default and has no multi-user authentication. To bind
to another interface you must both choose the host and acknowledge the exposure:

```bash
wallbreaker dashboard --host 0.0.0.0 --allow-network
```

Do this only behind an access-controlled boundary. Run history can contain prompts,
responses, reasoning, tool arguments, and generated artifacts.

## Frontend development

Keep `wallbreaker dashboard` running, then start the Vite development server in another
terminal:

```bash
cd wallbreaker/dashboard/web
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8787`. Frontend source changes hot-reload.
After Python backend changes, restart `wallbreaker dashboard`. To update the production
bundle served on port 8787, run `npm run build` again and refresh the browser.

## History and local state

| Path | Purpose |
|---|---|
| `config.toml` | Provider definitions, profiles, and active role configuration |
| `.env` | Optional locally managed provider credentials |
| `.wallbreaker_state.json` | Non-secret runtime preferences and UI references |
| `.wallbreaker_models.sqlite3` | Rebuildable provider model catalog |
| `sessions/run-*.jsonl` | Canonical portable execution history |
| `sessions/.wallbreaker_history.sqlite3` | Rebuildable search and correlation index |

JSONL is the source of truth. The SQLite history index may be deleted and rebuilt from
V2's Runs and Logs screen or through `POST /api/v2/history/rebuild`. Archive or remove
canonical run files only when you intend to remove that evidence.

## Verify the installation

Run the Python suite with the project environment and build the frontend:

```bash
python -m pytest tests
cd wallbreaker/dashboard/web
npm run build
```

The full Python suite needs the project environment because the TUI, dashboard, image,
and steganography tests use optional dependencies installed there.

## Troubleshooting

### The API runs but the browser UI is missing

Build the frontend with `npm run build`, then refresh. Without a production bundle the
backend returns a message explaining that only its API is available.

### Every provider request fails

Run `wallbreaker check`, then use **Models → Test provider**. A real test must authenticate
and query the configured provider; an authentication error is not a successful connection.
Check the key variable, base URL, protocol, authentication style, model path, and model ID.
Native Anthropic normally uses `x-api-key`; some compatible proxies require `bearer`.

### A run is absent from Live, Findings, or Reports

Confirm its `run-*.jsonl` file is in the directory passed through `--sessions` (default:
`sessions/`). In **Runs and Logs**, rebuild the history index. Malformed JSONL records are
retained as visible parse errors rather than silently discarded.

### Browser state appears stale

Hard-refresh after rebuilding the frontend. V2 keeps drafts, selected views, conversation
state, and workflow state while navigating; resetting or archiving a conversation is an
explicit action.
