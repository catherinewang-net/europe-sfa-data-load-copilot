# Streamlit Community Cloud deployment

Deploy PepFlow AI for a **shareable team demo** without requiring each teammate to clone the EUSFA Salesforce DX repository.

## Prerequisites

- GitHub repository access (company GitHub — see [Repo safety](#repo-safety) below)
- An audited `bundled_metadata/` snapshot committed to the repo
- (Optional) Salesforce Connected App for live org metadata via OAuth

## Limitations

| Capability | Local dev | Streamlit Community Cloud |
|------------|-----------|---------------------------|
| EUSFA git clone | Required (`METADATA_MODE=local`) | **Not available** — use `METADATA_MODE=bundled` |
| Bundled metadata snapshot | Optional | **Required** |
| Git pull / metadata sync | Yes (local mode) | No |
| Salesforce OAuth | Optional | Optional (secrets required) |
| Entra SSO (`st.login`) | Optional | Optional (secrets `[auth]` block) |
| Persistent OAuth tokens | Session only | Session only (Streamlit reruns) |

Community Cloud has **no persistent local filesystem** for a private EUSFA clone. The app defaults to `METADATA_MODE=bundled` when it detects a hosted environment (Streamlit Cloud user `appuser`, Docker, or `DEPLOYMENT_MODE=demo|production`).

## 1. Prepare the metadata snapshot (once, before deploy)

On a machine with access to the EUSFA SFDX repo:

```powershell
cd Europe-SFA-Data-Load-Copilot
$env:EUSFA_SFDX_REPO_PATH = "C:\path\to\EUROPE_SFA"
.\scripts\bundle_metadata_snapshot.ps1
python scripts\audit_bundled_metadata.py
```

Commit the generated `bundled_metadata/` directory (XML metadata only — no Apex, LWC, or secrets).

## 2. Create the Streamlit Cloud app

1. Push this repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and **Create app**.
3. Select the repository, branch, and main file: **`app.py`**
4. Python version: **3.11** (via `runtime.txt` in repo root).

## 3. Configure secrets

In **App settings → Secrets**, paste TOML based on `.streamlit/secrets.toml.example`.

Top-level string keys are promoted to environment variables and read by `core/config.py` via `os.environ` (and `python-dotenv` locally).

### Required for hosted demo (snapshot-only)

```toml
DEPLOYMENT_MODE = "demo"
METADATA_MODE = "bundled"
SSO_DISABLED = "true"
```

`SSO_DISABLED=true` skips Entra `st.login()` for internal team demos. Remove or set to `false` when Entra is configured.

### Optional — Salesforce OAuth (live org metadata)

Register a Salesforce **External Client App** or Connected App with:

- **Authorization Code + PKCE** (no client secret required)
- **Callback URL** exactly matching `SALESFORCE_REDIRECT_URI`

For Streamlit Community Cloud, the callback is the app root URL:

```toml
SALESFORCE_CLIENT_ID = "<connected-app-consumer-key>"
SALESFORCE_REDIRECT_URI = "https://<your-app-name>.streamlit.app/"
SALESFORCE_API_VERSION = "v59.0"
```

OAuth callback handling is implemented in `app.py` via `handle_oauth_callback(st.session_state, st.query_params)`. After authorization, Salesforce redirects to:

`https://<your-app-name>.streamlit.app/?code=...&state=...`

The app exchanges the code, stores tokens in **session state only**, and clears query params.

If OAuth secrets are **not** set, the Connect Salesforce card shows a warning and validation uses the **bundled snapshot only** — it does not claim live metadata.

### Optional — Entra ID SSO (app-level gate)

Separate from Salesforce OAuth. Only needed when `DEPLOYMENT_MODE=demo|production` and `SSO_DISABLED` is unset:

```toml
[auth]
redirect_uri = "https://<your-app-name>.streamlit.app/oauth2callback"
cookie_secret = "<long-random-string>"
client_id = "<entra-client-id>"
client_secret = "<entra-client-secret>"
server_metadata_url = "https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration"
```

Register the Entra redirect URI in Azure App Registration.

### All deployment secrets reference

| Secret / env var | Required | Purpose |
|------------------|----------|---------|
| `DEPLOYMENT_MODE` | Recommended | `demo` for team demo; affects SSO default |
| `METADATA_MODE` | **Yes on Cloud** | Must be `bundled` (default on hosted) |
| `SSO_DISABLED` | Demo only | `true` to skip Entra login |
| `SALESFORCE_CLIENT_ID` | OAuth only | Connected App consumer key |
| `SALESFORCE_REDIRECT_URI` | OAuth only | Must match Salesforce callback URL |
| `SALESFORCE_API_VERSION` | Optional | Default `v59.0` |
| `SALESFORCE_OAUTH_SCOPES` | Optional | Default `api refresh_token id` |
| `BUNDLED_METADATA_PATH` | Optional | Override snapshot path (default `bundled_metadata/`) |
| `REQUIRE_SSO` | Optional | Force Entra gate when set truthy |
| `SSO_ENABLED` | Optional | Force Entra on local dev for testing |
| `[auth].*` | Entra only | Streamlit OIDC — see above |

Legacy env-based Salesforce credentials (`SF_ACCESS_TOKEN`, etc.) are deprecated; use OAuth connection in the UI.

## 4. Verify before sharing the URL

**Do not share the app URL until startup succeeds.**

Locally simulate Cloud mode:

```powershell
$env:DEPLOYMENT_MODE = "demo"
$env:METADATA_MODE = "bundled"
$env:SSO_DISABLED = "true"
python -m streamlit run app.py
```

Checklist:

- [ ] App loads without `Metadata startup validation failed`
- [ ] Connect Salesforce card shows honest state (snapshot vs OAuth configured)
- [ ] Template dropdown populates from bundled snapshot
- [ ] Demo CSV validates: `test_data/retail_promotion/RO_Promotion_Faulty_Validation_Test.csv`
- [ ] `python scripts/audit_bundled_metadata.py` passes
- [ ] `pytest` passes

## 5. Share with the team

Share the `https://<your-app-name>.streamlit.app/` URL.

Teammates do **not** need a local EUSFA clone for snapshot-mode validation. For live org picklists/fields, each user connects their own Salesforce org via OAuth (when configured).

## Repo safety

### Safe to commit

- Application source code (`app.py`, `services/`, `ui/`, etc.)
- `requirements.txt`, `runtime.txt`, `.streamlit/config.toml`
- `bundled_metadata/` after `audit_bundled_metadata.py` passes (validation XML only)
- `test_data/` demo CSVs
- `.streamlit/secrets.toml.example` (placeholders only)
- `.env.example` (no real values)

### Never commit

- `.env`, `.streamlit/secrets.toml`
- OAuth tokens, refresh tokens, API keys
- Full EUSFA git repository clone
- User-uploaded CSVs from production
- Confidential logs
- Absolute paths to developer machines in runtime code

### Bundled metadata sensitivity

The snapshot contains **Salesforce object/field/picklist definitions** (company configuration metadata). It is not customer PII, but treat it as internal IP:

- Run `python scripts/audit_bundled_metadata.py` before every bundle update
- Do not include Apex, LWC, static resources, or `.git` history (bundle script excludes these)
- Prefer a private GitHub repository for the Copilot repo

### Git history

If `.env` or tokens were ever committed, rotate credentials and use `git filter-repo` or BFG before pushing to company GitHub.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Metadata startup validation failed: Bundled metadata manifest not found` | Run bundle script and commit `bundled_metadata/` |
| `NameError: get_bundled_metadata_dir` | Update to latest code (startup validation fix) |
| OAuth redirect mismatch | Match `SALESFORCE_REDIRECT_URI` to Connected App callback exactly |
| Entra login loop | Set `SSO_DISABLED=true` for demo, or configure `[auth]` block |
| Template list empty | Rebuild bundled snapshot; verify `customMetadata` templates exist |
| App requires local path | Set `METADATA_MODE=bundled` in Cloud secrets |

## Related docs

- [README.md](../../README.md) — local setup
- [PHASE1_DEMO_DEPLOYMENT.md](./PHASE1_DEMO_DEPLOYMENT.md) — Azure Container Apps demo
- [TEAM_SETUP.md](../TEAM_SETUP.md) — local teammate onboarding
