# Skillvaya

Python standard-library web app. Local launch: `python run_local.py`; local URL: `http://127.0.0.1:8877`.

## Deployment staging
- `render.yaml` configures a Render web service and 1 GB persistent disk. It is a deployment blueprint, not a live service.
- The current Android app can be built with `SKILLVAYA_PUBLIC_URL` to load the same hosted marketplace. The Windows launcher reads `SKILLVAYA_PUBLIC_URL` or `deployment.json` for hosted mode.
- Keep the service to one instance while using SQLite on the persistent disk; every user then shares the same database.
- Do not expose a public launch until owner authentication, session expiry/revocation, rate limiting, CSRF/security headers and backups are reviewed and tested.
- Keep PayFast in sandbox until public HTTPS callback delivery and checkout/refund tests pass.
- Set all merchant credentials and owner password as hosting secret environment variables; never commit them.

See `README.md`, `DEPLOYMENT_STAGING_CHECKLIST.md` and `DEPLOYMENT_READINESS.md`.
