# Skillvaya

Python standard-library web app. Local launch: `python run_local.py`; local URL: `http://127.0.0.1:8877`.

## Deployment staging
- `render.yaml` is a deployment blueprint scaffold, not a live service.
- Do not deploy publicly until owner authentication and session/CSRF protections are reviewed and tested.
- Keep PayFast in sandbox until public HTTPS callback delivery and checkout are proven end-to-end.
- Set all merchant credentials as hosting secret environment variables; never commit them.
- Production data must use persistent storage and a tested backup/restore process.

See `DEPLOYMENT_STAGING_CHECKLIST.md` and `DEPLOYMENT_READINESS.md`.
