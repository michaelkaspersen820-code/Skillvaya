# Skillvaya deployment staging checklist

`render.yaml` is a deployment scaffold, not a live service. It sets a persistent SQLite path, a health check, and server-side-only PayFast secret fields. Never commit live credentials.

## Mandatory release blockers before a public launch
- Implement and verify authenticated owner access; the current owner console uses a loopback-only developer bypass and must not be exposed as an unauthenticated public admin panel.
- Confirm production-grade session expiry/revocation, CSRF protection, rate limiting, request logging, and backup/restore.
- Create a private Git repository and connect it to the hosting account; no repository is currently available through the connected GitHub account.
- Configure the hosting service and persistent disk; no hosting account has been configured from the connected tools.
- Configure sandbox merchant credentials and the public HTTPS callback, run a real sandbox checkout, validate PayFast ITN delivery, and test refunds before considering live mode.
- Set SMTP secrets and verify send/receive; receiving Gmail inside the app requires separate OAuth work.
- Keep `SKILLVAYA_PAYFAST_MODE=sandbox` until the release gates pass. Switch to `live` only after account verification and explicit production checks.

## Hosting variables
- `SKILLVAYA_DB_PATH=/var/data/skillvaya.sqlite3` (persistent disk mount)
- `SKILLVAYA_PUBLIC_URL=https://<assigned-service-hostname>`
- `SKILLVAYA_PAYFAST_MODE=sandbox`
- `SKILLVAYA_PAYFAST_MERCHANT_ID`, `SKILLVAYA_PAYFAST_MERCHANT_KEY`, `SKILLVAYA_PAYFAST_PASSPHRASE` (host secret settings only)

Render deployment requires a connected Git repository and the service to bind to the provided `PORT`; its filesystem is ephemeral unless persistent storage is attached. See official docs: https://render.com/docs/web-services and https://render.com/docs/disks.
