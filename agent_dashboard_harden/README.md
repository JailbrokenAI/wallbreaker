# agent_dashboard_harden

A re-export facade for Wallbreaker's security hardening toolkit. Consuming projects import from a single stable path rather than from internal wallbreaker modules.

## Exported symbols

| Symbol | Source |
|---|---|
| `SecurityMiddleware` | `wallbreaker.dashboard.auth` |
| `ensure_launch_token` | `wallbreaker.dashboard.auth` |
| `origin_is_same_site` | `wallbreaker.dashboard.auth` |
| `token_file_path` | `wallbreaker.dashboard.auth` |
| `EgressBlocked` | `wallbreaker.tools.egress_guard` |
| `check_url` | `wallbreaker.tools.egress_guard` |
| `PinnedEgressBackend` | `wallbreaker.tools.egress_guard` |
| `make_pinned_transport` | `wallbreaker.tools.egress_guard` |
| `build_dashboard_registry` | `wallbreaker.tools.tool_policy` |

## ≤1-iteration wiring example

```python
# myapp/server.py
from fastapi import FastAPI
from agent_dashboard_harden import SecurityMiddleware, build_dashboard_registry, ensure_launch_token

def create_my_app(config, sessions_dir, *, require_auth: bool = True):
    token = ensure_launch_token(sessions_dir) if require_auth else ""
    app = FastAPI()
    app.add_middleware(SecurityMiddleware, token=token, require_auth=require_auth)

    registry = build_dashboard_registry(config)   # host tools excluded by default
    # … register routes …
    return app
```

## PBT fixtures in conftest.py

```python
# tests/conftest.py
from agent_dashboard_harden import check_url, ensure_launch_token, token_file_path
from agent_dashboard_harden.pbt_fixtures import (
    make_input_validation_property,
    make_session_property,
)

# Wire SP-2: URL validation property
test_url_validation = make_input_validation_property(check_url)

# Wire SP-5: token file permission property
def _write_token(tmp_path):
    ensure_launch_token(tmp_path)
    return token_file_path(tmp_path)

test_token_perms = make_session_property(_write_token)
```

Run the properties:

```bash
pytest tests/conftest.py -q
```
