# Salesforce OAuth — Europe SFA Data Load Copilot

Salesforce OAuth is the **primary** authentication path for live org metadata. Microsoft Entra SSO (`st.login()`) remains an optional app-level gate configured separately and does not replace Salesforce connection.

## Architecture

| Component | Role |
|-----------|------|
| `services/salesforce_oauth_service.py` | PKCE authorize URL, token exchange, session-scoped tokens |
| `services/salesforce/live_metadata_provider.py` | REST Describe + UI API picklists |
| `services/salesforce/hybrid_metadata_provider.py` | Live fields/picklists + repository templates |
| `ui/salesforce_connection.py` | Connection card UI |
| `app.py` | OAuth callback via `st.query_params` before main UI |

## Connected App setup

1. In Salesforce Setup, create an **External Client App** (or Connected App) with:
   - **OAuth settings enabled**
   - **Authorization Code and Credentials Flow** (PKCE required for public clients)
   - **Callback URL** — must match `SALESFORCE_REDIRECT_URI` exactly

2. Copy the **Consumer Key** into `SALESFORCE_CLIENT_ID`.

3. No client secret is required for PKCE public-client flow.

### Callback URLs by host

| Deployment | Register this callback URL |
|------------|----------------------------|
| Local dev (`streamlit run app.py`) | `http://localhost:8501/` |
| Streamlit Community Cloud | `https://<your-app>.streamlit.app/` |
| Azure Container Apps | `https://<container-app-fqdn>/` |

Example:

```env
SALESFORCE_CLIENT_ID=3MVG9...
SALESFORCE_REDIRECT_URI=https://eusfa-copilot.example.com/
SALESFORCE_API_VERSION=v59.0
```

## OAuth scopes

Default (`SALESFORCE_OAUTH_SCOPES`):

```
api refresh_token id
```

| Scope | Purpose |
|-------|---------|
| `api` | REST Describe, query, UI API for metadata |
| `refresh_token` | Optional token refresh (v1 stores in session only) |
| `id` | User identity URL for org/user display |

## User flow

1. Open Copilot → **Salesforce Connection** card shows *Not connected*.
2. Choose Production/Developer Org or Sandbox → **Connect Salesforce**.
3. Browser redirects to `login.salesforce.com` or `test.salesforce.com`.
4. User signs in and approves.
5. Salesforce redirects to `SALESFORCE_REDIRECT_URI?code=...&state=...`.
6. `app.py` exchanges the code immediately, clears query params, stores tokens in `st.session_state`.
7. Connected card shows org, environment, user, instance, last refreshed.
8. Field/picklist validation uses live Describe; templates still use bundled/local snapshot.

## Session isolation (v1)

- Tokens live in **`st.session_state` only** — not persisted across browser restarts or server replicas.
- Users must reconnect when the session expires or the server restarts.
- No tokens appear in UI text, logs, CSV exports, or shared caches.
- OAuth `code` appears only briefly in the URL and is exchanged on the next app load.

## Entra SSO (optional)

Set in `.env`:

```env
SSO_DISABLED=true          # local dev default
REQUIRE_SSO=true           # force Entra gate in any deployment mode
```

Entra config lives in `.streamlit/secrets.toml` (see `.streamlit/secrets.toml.example`). When `SSO_DISABLED=true`, Salesforce OAuth works without Entra login.

## Streamlit Community Cloud

Community Cloud supports this flow:

- Register the app URL (`https://<app>.streamlit.app/`) as the Salesforce callback.
- Set secrets via the Cloud dashboard (equivalent to env vars).
- Query-param callback (`?code=&state=`) is handled at the top of `app.py` before rendering.

Limitation: session-only tokens — each new browser session requires reconnecting to Salesforce.

## Fallback behaviour

When not connected, validation uses **Snapshot validation** (bundled metadata in Docker/demo) or the local SFDX clone (`METADATA_MODE=local`). The UI labels this clearly on the connection card.
