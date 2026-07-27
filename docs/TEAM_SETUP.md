# Team setup — Europe SFA Data Load Copilot

This guide gets a teammate from zero to a running Copilot on **Windows** (PepsiCo standard). Each person runs the app locally because validation reads **your local EUSFA Salesforce DX metadata clone**.

## Recommended approach

**Local install + one-command launcher** (`scripts/run_copilot.ps1`).

| Approach | Why |
|----------|-----|
| **Local install (recommended)** | Metadata lives on disk; Git fetch/pull is built in; no shared secrets; works on corporate VPN. |
| Docker | Possible but adds little value — you still mount the EUSFA repo and configure `.env`. Not provided by default. |
| Streamlit Community Cloud | **Not suitable** — requires a local/metadata filesystem path and optional live Salesforce credentials. |

---

## What each teammate needs

1. **Git** — clone this Copilot repo and the EUSFA Salesforce DX metadata repo.
2. **Python 3.11+** — [python.org downloads](https://www.python.org/downloads/) (check **Add Python to PATH**).
3. **Access to the EUSFA metadata repository** — ask your Salesforce / release manager for clone URL and permissions.
4. **Optional:** Salesforce credentials for **live record lookup** only (validation works without them).

---

## Quick start (Windows)

### 1. Clone the Copilot

```powershell
git clone <copilot-repo-url>
cd Europe-SFA-Data-Load-Copilot
```

### 2. Clone EUSFA Salesforce metadata

Clone to any folder you prefer. Default expected by the Copilot:

```powershell
git clone <eusfa-sfdx-repo-url> "$env:USERPROFILE\.cursor\EUSFA SF\EUROPE_SFA"
```

The folder must contain `sfdx-project.json` and `force-app/main/default/`.

### 3. Configure environment

```powershell
copy .env.example .env
notepad .env
```

Set at minimum:

```ini
EUSFA_SFDX_REPO_PATH=C:\Users\<you>\.cursor\EUSFA SF\EUROPE_SFA
```

Use your actual path if you cloned elsewhere.

### 4. Run the app

```powershell
.\scripts\run_copilot.ps1
```

Or double-click `scripts\run_copilot.bat`.

The script creates `venv`, installs dependencies, loads `.env`, and opens Streamlit at **http://localhost:8501**.

Custom port:

```powershell
.\scripts\run_copilot.ps1 -Port 8502
```

---

## Manual setup (alternative)

```powershell
cd Europe-SFA-Data-Load-Copilot
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env — set EUSFA_SFDX_REPO_PATH
streamlit run app.py
```

---

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `EUSFA_SFDX_REPO_PATH` | **Yes** (or use default path) | Root of local EUSFA SFDX clone |
| `SF_INSTANCE_URL` | No | Live lookup — org URL |
| `SF_ACCESS_TOKEN` | No | Live lookup — session token |
| `SF_USERNAME` | No | Live lookup — username auth |
| `SF_PASSWORD` | No | Live lookup — password |
| `SF_SECURITY_TOKEN` | No | Appended to password for login flow |
| `SF_DOMAIN` | No | Default `login`; use `test` for sandbox |
| `SF_CLIENT_ID` | No | Connected App (password flow) |
| `SF_CLIENT_SECRET` | No | Connected App (password flow) |

**Without Salesforce credentials:** use **Prepare & Validate File** and check **Skip live Salesforce record check** when prompted. Picklist and field validation still use local metadata.

Never commit `.env`. Copy from `.env.example` only.

---

## Try the demo CSV

After the app is running and metadata shows as connected:

1. **Upload method:** Data Import Tool  
2. **Template:** Retail Promotion  
3. **Task:** Prepare & Validate File  
4. Upload:

   `test_data/retail_promotion/RO_Promotion_Faulty_Validation_Test.csv`

This file injects common faults (dates, picklists, duplicates, blanks) so you can confirm validation is working.

Other samples in the same folder:

- `RO_Promotion_Malformed_Row_Test.csv`
- `RO_Promotion_Fault_Injection_Log.csv` (documents injected faults)

---

## Metadata refresh in the app

Use the **Salesforce Metadata Source** panel at the top:

| Action | Effect |
|--------|--------|
| **Refresh Local Metadata** | Reload XML from your local clone (no Git pull) |
| **Check for Salesforce Updates** | `git fetch` + compare with remote |
| **Pull Approved Salesforce Updates** | Fast-forward pull when remote is ahead and tree is clean |

After metadata changes during a session, the app may warn that validation was tied to an earlier commit — re-upload or refresh as needed.

See also [METADATA_SYNC.md](METADATA_SYNC.md).

---

## Troubleshooting

### “Metadata not connected” / validation unavailable

**Symptoms:** Red or warning state in **Salesforce Metadata Source**; message that fields and picklists cannot be validated.

**Checks:**

1. `EUSFA_SFDX_REPO_PATH` in `.env` points to the **SFDX project root** (not `force-app/main/default`).
2. Folder exists and contains `sfdx-project.json`.
3. `force-app/main/default/` exists under that root.
4. Click **Refresh Local Metadata** after fixing the path.
5. Restart the app if you changed `.env` outside the launcher script.

**Default path if unset:**

```
%USERPROFILE%\.cursor\EUSFA SF\EUROPE_SFA
```

### `python` not found / wrong Python version

- Install Python **3.11+** and enable **Add to PATH**.
- In PowerShell: `python --version` should show 3.11 or higher.

### PowerShell script execution blocked

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Or use `run_copilot.bat`, which bypasses policy for the script call.

### Git actions fail in the app

- Ensure Git is installed: `git --version`
- Metadata folder must be a Git repo for fetch/pull (validation still works from files if Git is missing, but sync buttons may fail).
- Corporate proxy: configure Git SSL/proxy per IT guidance.

### Live Salesforce connection errors

- Confirm optional `SF_*` variables in `.env`.
- Use **Skip live Salesforce record check** for offline/formatting-only work.
- Token auth: both `SF_INSTANCE_URL` and `SF_ACCESS_TOKEN` required.
- Username auth: `SF_USERNAME` + `SF_PASSWORD`; security token appended automatically.

### Streamlit port already in use

```powershell
.\scripts\run_copilot.ps1 -Port 8502
```

### Dependencies / import errors

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

For tests: `pip install -r requirements-dev.txt` then `pytest`.

---

## Sharing this repo with your team

**As the repo owner:**

1. Push the Copilot to your team Git remote (GitHub, Azure DevOps, etc.).
2. Share this document: `docs/TEAM_SETUP.md`.
3. Provide teammates:
   - Copilot clone URL
   - **EUSFA Salesforce DX repo URL** and access instructions
   - Optional: sandbox credentials policy for live lookup
4. Confirm they do **not** commit `.env`.

**As a new teammate:**

1. Clone Copilot → clone EUSFA metadata → copy `.env.example` to `.env` → run `.\scripts\run_copilot.ps1`.
2. Verify metadata panel shows connected.
3. Run the Retail Promotion demo CSV above.

---

## Python version

**Python 3.11+** (matches `README.md` and project tooling).

---

## Security notes

- `.env` is gitignored; never add real paths or Salesforce secrets to the repo.
- Live Salesforce access is **read-only** (SOQL queries for record existence).
- The Copilot does not modify the EUSFA metadata repository automatically; Git pull requires explicit confirmation in the UI.

---

## Related docs

- [README.md](../README.md) — project overview
- [PROJECT.md](../PROJECT.md) — architecture
- [METADATA_SYNC.md](METADATA_SYNC.md) — metadata cache and Git sync design
