# Metadata sync architecture

This document describes how the Europe SFA Data Load Copilot reads local Salesforce metadata and how future CI can validate compatibility. No CI pipeline is implemented yet.

## Components

```
ui/metadata_source.py
    └── services/metadata_refresh_service.py  → adapters/sfdx_metadata/adapter.py
    └── services/git_repository_service.py    → local EUSFA SFDX Git clone
```

### Configuration

- `core/config.py` exposes `EUSFA_SFDX_REPO_PATH` (environment variable or default under the user profile).
- All services and UI read this path; no hardcoded developer machine paths.

### Adapter cache

- `get_metadata_adapter()` caches one `SfdxMetadataAdapter` instance per repository path in-process.
- `clear_metadata_adapter_cache()` drops cached adapters so XML/metadata is re-read from disk.
- `refresh_metadata()` also resets the template dropdown cache in `services/template_service.py`.

### Git sync (read-only from the Copilot's perspective)

- `git_repository_service.py` runs fixed Git subprocess commands only (`fetch`, `status`, `pull --ff-only`).
- No auto-pull, no `reset --hard`, no `clean`, no merge/rebase.
- Non-fast-forward situations return a user-facing message and leave the working tree unchanged.

### Session version lock

- On CSV upload, `app.py` stores `st.session_state["metadata_version"]` as the current commit hash.
- After metadata refresh or pull, if the commit hash differs, the app warns that validation may be stale for the current session.

## Future CI hooks (planned, not implemented)

### 1. Adapter validation tests

Run in CI against a pinned checkout of the EUSFA SFDX repository:

- Smoke-load metadata via `SfdxMetadataAdapter.from_default_repo()` (or a fixture path).
- Assert minimum counts for objects, fields, templates, and zero unexpected skipped files.
- Re-use patterns from `tests/test_metadata_refresh_service.py` with a known metadata snapshot.

### 2. Compatibility report

After loading metadata, generate a report (JSON or markdown artifact) that includes:

- Repository commit hash and refresh timestamp
- Template names vs `core/config.TEMPLATES` / `rules/tool_mappings.json`
- Objects referenced by active templates that are missing from metadata
- Picklist fields used by validators with empty allowed-value sets

Hook this into CI as a non-blocking or gated check when the SFDX repo advances, so Copilot releases can be tied to tested metadata revisions.

### 3. Git sync in automation

CI should **not** auto-pull production metadata into developer clones. Instead:

- Pin `EUSFA_SFDX_REPO_PATH` in CI to a submodule or cached clone at a known commit.
- Run adapter tests and compatibility report against that pin.
- Document the tested commit in release notes.

## Manual operator workflow

1. Clone or update the EUSFA SFDX repo outside the Copilot when needed.
2. Set `EUSFA_SFDX_REPO_PATH` if not using the default location.
3. In the app: **Refresh Local Metadata** after local file changes; **Check for Salesforce Updates** then **Pull Approved Salesforce Updates** when remote changes are approved.
