# PepFlow AI

**Prepare. Validate. Load.**

Prepare and validate CSV files before uploading them into Salesforce using live org metadata or an approved EUSFA metadata snapshot.

## Share with your team

Teammates run PepFlow AI **locally** (each person needs their own EUSFA metadata clone). Full onboarding, env vars, demo CSV, and troubleshooting:

**→ [docs/TEAM_SETUP.md](docs/TEAM_SETUP.md)**

**Fastest path on Windows:**

```powershell
git clone <copilot-repo-url>
cd Europe-SFA-Data-Load-Copilot
copy .env.example .env
# Edit .env — set EUSFA_SFDX_REPO_PATH to your EUROPE_SFA clone
.\scripts\run_copilot.ps1
```

Demo file after setup: `test_data/retail_promotion/RO_Promotion_Faulty_Validation_Test.csv` (Retail Promotion template).

## Prerequisites

- Python 3.11+
- Git (for optional Salesforce repository sync)
- A local clone of the EUSFA Salesforce DX repository

## Setup

1. Clone this Copilot repository:

```bash
git clone <copilot-repo-url>
cd Europe-SFA-Data-Load-Copilot
```

2. Create a virtual environment and install dependencies:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

3. Clone the EUSFA Salesforce metadata repository to a local path of your choice:

```bash
git clone <eusfa-sfdx-repo-url> "%USERPROFILE%\.cursor\EUSFA SF\EUROPE_SFA"
```

4. Point PepFlow AI at your local Salesforce metadata clone (optional if using the default path above):

```powershell
$env:EUSFA_SFDX_REPO_PATH = "C:\path\to\EUROPE_SFA"
```

The app reads metadata from `EUSFA_SFDX_REPO_PATH` only. It never modifies Salesforce repository files automatically.

## Run the app

```bash
streamlit run app.py
```

**Windows (recommended):** `.\scripts\run_copilot.ps1` — creates venv, installs deps, loads `.env`. See [docs/TEAM_SETUP.md](docs/TEAM_SETUP.md).

## Salesforce metadata refresh

Use the **Metadata Source** panel at the top of the app:

| Action | What it does |
|--------|----------------|
| **Refresh Local Metadata** | Clears the in-process adapter cache and reloads metadata from your local clone. Does not run Git pull. |
| **Check for Salesforce Updates** | Runs `git fetch` and compares your branch with its remote tracking branch. Does not change files. |
| **Pull Approved Salesforce Updates** | Available only after updates are detected, the working tree is clean, and you confirm. Runs a fast-forward-only pull, then refreshes metadata. |

If a non-fast-forward update is required, the Copilot stops and asks you to resolve Git conflicts manually outside the app.

### Session metadata version lock

When you upload a CSV, PepFlow AI records the current Salesforce metadata commit hash for that session. If metadata changes later (refresh or pull), you will see a warning that validation may no longer match the version used when you started.

## Project layout

See [PROJECT.md](PROJECT.md) for architecture. Metadata sync design notes for future CI are in [docs/METADATA_SYNC.md](docs/METADATA_SYNC.md).

## Tests

```bash
pytest
```

## Leadership demo deployment (Phase 1)

Hosted demo runs on **Azure Container Apps** with optional **Entra ID SSO** and a **bundled read-only EUSFA metadata snapshot**. Connect Salesforce via OAuth for live org metadata.

1. Bundle metadata: `.\scripts\bundle_metadata_snapshot.ps1`
2. Audit: `python scripts\audit_bundled_metadata.py`
3. Build: `docker build -t eusfa-copilot:demo .`
4. Deploy: follow [docs/deployment/PHASE1_DEMO_DEPLOYMENT.md](docs/deployment/PHASE1_DEMO_DEPLOYMENT.md)

Rollback: [docs/deployment/ROLLBACK_PLAN.md](docs/deployment/ROLLBACK_PLAN.md)

| Variable | Local dev | Docker / ACA demo |
|----------|-----------|-------------------|
| `DEPLOYMENT_MODE` | `local` | `demo` |
| `METADATA_MODE` | `local` | `bundled` |
| `SSO_DISABLED` | `true` (optional) | unset |
| Metadata path | `EUSFA_SFDX_REPO_PATH` | `/app/bundled_metadata` |

Phase 2 (live Salesforce OAuth metadata) is implemented — see [docs/SALESFORCE_OAUTH.md](docs/SALESFORCE_OAUTH.md).

## Streamlit Community Cloud (team demo)

Share a URL with teammates — **no local EUSFA clone required** when using the bundled metadata snapshot.

**→ [docs/deployment/STREAMLIT_COMMUNITY_CLOUD.md](docs/deployment/STREAMLIT_COMMUNITY_CLOUD.md)**

Quick Cloud secrets (snapshot-only demo):

```toml
DEPLOYMENT_MODE = "demo"
METADATA_MODE = "bundled"
SSO_DISABLED = "true"
```

Main file: `app.py` · Python: 3.11 (`runtime.txt`) · Do not deploy until startup validation passes locally with `METADATA_MODE=bundled`.
