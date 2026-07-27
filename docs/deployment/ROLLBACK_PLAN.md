# Rollback Plan — Phase 1 Leadership Demo

Use this plan if the Azure Container Apps deployment fails validation, exposes the app anonymously, or ships a bad metadata snapshot.

## Rollback triggers

- Entra SSO bypass (users reach app without login)
- `audit_bundled_metadata.py` findings discovered post-deploy
- Container crash loop / health check failures
- Validation regressions vs. local dev baseline
- Leadership demo blocked by auth or metadata errors

## Immediate rollback (< 5 minutes)

### Option A — Revert to previous ACA revision (preferred)

```bash
az containerapp revision list \
  --name eusfa-copilot-demo \
  --resource-group rg-eusfa-copilot-demo \
  -o table

az containerapp revision activate \
  --name eusfa-copilot-demo \
  --resource-group rg-eusfa-copilot-demo \
  --revision <previous-stable-revision-name>
```

### Option B — Scale to zero / disable ingress

```bash
az containerapp ingress disable \
  --name eusfa-copilot-demo \
  --resource-group rg-eusfa-copilot-demo
```

Or set min replicas to 0 until fixed.

### Option C — Entra app disable

In Entra ID → Enterprise applications → disable user sign-in for the Copilot app registration.  
Effect: instant auth wall even if container is still running.

## Full teardown

```bash
az containerapp delete --name eusfa-copilot-demo --resource-group rg-eusfa-copilot-demo --yes
# Retain ACR images for forensics; delete image tag only after incident review
```

## Bad metadata snapshot

1. Do **not** rebuild from un-audited source.
2. Identify last known-good image tag in ACR.
3. Activate revision with that tag.
4. Re-run local `bundle_metadata_snapshot.ps1` + audit on fixed source commit.
5. Deploy new tag only after audit pass and pytest green.

## Auth misconfiguration

| Symptom | Fix |
|---------|-----|
| Redirect URI mismatch | Update Entra app + `secrets.toml` redirect_uri to match ACA FQDN |
| Anonymous access | Ensure `DEPLOYMENT_MODE=demo` and `SSO_DISABLED` is not set |
| Login loop | Verify `cookie_secret` stable across replicas; use sticky sessions or single replica for demo |

## Communication template

> The leadership demo Copilot has been rolled back to the previous stable revision due to [issue].  
> The app is unavailable / restored at [URL]. No Salesforce data was modified.  
> Metadata snapshot commit: [hash from SNAPSHOT_MANIFEST.json].

## Recovery checklist

- [ ] Root cause documented
- [ ] Audit script re-run on new bundle
- [ ] Full pytest suite passed locally
- [ ] SSO verified in incognito browser
- [ ] Sample CSV validation smoke test passed
- [ ] New revision deployed with updated manifest hash
