## [ERR-20260810-001] cross-pr-capability-parity

**Logged**: 2026-08-10T00:00:00+02:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
Merging a PR that adds a TUI slash command with the WebUI V2 capability catalog requires adding the command to exactly one catalog category.

### Error
`RuntimeError: TUI capability '/liberate' has 0 categories`

### Context
PR #24 added `/liberate` and `/memory`; PR #25 derives an import-time capability manifest from `KNOWN_COMMANDS`.

### Suggested Fix
Whenever `KNOWN_COMMANDS` changes, update `_CATEGORY_COMMANDS` and add a catalog parity test.

### Metadata
- Reproducible: yes
- Related Files: `wallbreaker/capabilities.py`, `wallbreaker/tui/app.py`

### Resolution
- **Resolved**: 2026-08-10T00:00:00+02:00
- **Notes**: Categorized `/liberate` and `/memory` under operations and added regression coverage.
