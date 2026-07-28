# Daedalus Desktop

Native desktop shell for [Daedalus / wallbreaker](https://github.com/JailbrokenAI/wallbreaker).

```
┌──────────────────────────────────────────────┐
│  Electron shell (tray · menu · single inst.) │
│  ┌────────────────────────────────────────┐  │
│  │  Daedalus Dashboard (React SPA)     │  │
│  │  + Desktop settings panel / status     │  │
│  └──────────────────▲─────────────────────┘  │
│                     │ HTTP / SSE / IPC       │
│  ┌──────────────────┴─────────────────────┐  │
│  │  wallbreaker dashboard (FastAPI)       │  │
│  │  agent loop · tools · judge · sessions │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

## Prerequisites

From the repo root:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -e ".[dev,dashboard]"

cd wallbreaker/dashboard/web
npm install
npm run build
cd ../../..
```

Node.js 20+ recommended.

## Dev launch

```bash
cd desktop
npm install
npm run dev
```

Boot sequence:

1. Build Electron main/preload
2. Ensure dashboard `dist/` exists
3. Spawn `.venv` Python: `python -m wallbreaker dashboard`
4. Wait for `/api/config`
5. Load dashboard in a native window

## Package (Windows)

```bash
cd desktop
npm run dist:win
# -> desktop/release/
```

Packaged builds still need a Wallbreaker checkout + venv (or `WALLBREAKER_ROOT`).

## Features

| Feature | Status |
|---------|--------|
| Auto-start / stop Python backend | ✅ |
| Reuse already-running dashboard | ✅ |
| Health monitor + auto-reconnect | ✅ |
| System tray with live status color | ✅ |
| Close-to-tray + single-instance | ✅ |
| Native menu / tab shortcuts | ✅ |
| Global show-hide `Ctrl+Shift+W` | ✅ |
| Splash + error log surface | ✅ |
| Desktop settings UI (in Settings tab) | ✅ |
| Backend log live stream | ✅ |
| File pickers for python/config | ✅ |
| Desktop status pill in topbar | ✅ |
| Live Terminal page (agent/backend/console) | ✅ |
| COMPLIED desktop notifications | ✅ |
| Auto port fallback when 8787 is busy | ✅ |
| Command palette (`Ctrl+K`) | ✅ |
| Environment diagnostics | ✅ |
| Export / copy logs | ✅ |
| Per-tab error boundaries | ✅ |
| Window bounds persistence | ✅ |
| Brand icon | ✅ |
| NSIS + portable Windows targets | ✅ |

## In-app Desktop settings

Open **Settings** (or `Ctrl+,`) while running in the shell:

- host / port
- python path override
- config path override
- close to tray / start minimized
- auto-reconnect / open DevTools
- restart backend
- open project / sessions folders
- live backend log

## IPC bridge

`window.wallbreakerDesktop` (preload, context-isolated):

- `getStatus` / `onStatus`
- `getSettings` / `patchSettings`
- `getLog` / `onLog`
- `getInfo`
- `restartBackend`
- `openPath` / `openExternal` / `pickFile`

## Environment

| Var | Purpose |
|-----|---------|
| `WALLBREAKER_ROOT` | Absolute path to the Wallbreaker repo |

## Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Command palette |
| `Ctrl+/` | Shortcuts sheet |
| `Ctrl+1`…`9` | Navigate tabs (4 = Terminal) |
| `Ctrl+R` | Reload UI |
| `Ctrl+Shift+R` | Restart backend |
| `Ctrl+Shift+D` | Run diagnostics |
| `Ctrl+,` | Desktop settings |
| `Ctrl+Shift+W` | Show / hide window |
| `Ctrl+Shift+I` | DevTools |

## Responsible use

Same policy as Wallbreaker: **authorized red-teaming only**.
