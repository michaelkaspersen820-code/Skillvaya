# Skillvaya deployment staging checklist

`render.yaml` is a deployment blueprint scaffold, not a live service. It configures a persistent SQLite path, health check, and host-only secret fields. Never commit live credentials.

## Mandatory release blockers before a public launch
- The app now bootstraps an owner account from `SKILLVAYA_OWNER_EMAIL` and `SKILLVAYA_OWNER_PASSWORD`; public startup fails closed unless the owner email is valid and the unique owner password is at least 14 characters. Verify this in the hosting environment before launch.
- Confirm production-grade session expiry/revocation, CSRF protection, rate limiting, request logging, and backup/restore.
- Create a private Git repository and connect it to the hosting account; no repository is currently available through the connected GitHub account.
- Configure the hosting service and persistent disk; no hosting account has been configured from the connected tools.
- Configure sandbox merchant credentials and the public HTTPS callback, run a real sandbox checkout, validate PayFast ITN delivery, and test refunds before considering live mode.
- Set SMTP secrets and verify send/receive; receiving Gmail inside the app requires separate OAuth work.
- Keep `SKILLVAYA_PAYFAST_MODE=sandbox` until the release gates pass. Switch to `live` only after account verification and explicit production checks.

## Hosting variables
- `SKILLVAYA_DB_PATH=/var/data/skillvaya.sqlite3` (persistent disk mount)
- `SKILLVAYA_PUBLIC_URL=https://<assigned-service-hostname>`
- `SKILLVAYA_OWNER_EMAIL` and `SKILLVAYA_OWNER_PASSWORD` (host secret settings only)
- `SKILLVAYA_PAYFAST_MODE=sandbox`
- `SKILLVAYA_PAYFAST_MERCHANT_ID`, `SKILLVAYA_PAYFAST_MERCHANT_KEY`, `SKILLVAYA_PAYFAST_PASSPHRASE` (host secret settings only)

Render requires a connected Git repository and the service to bind to its provided `PORT`; its filesystem is ephemeral unless persistent storage is attached. Official docs: https://render.com/docs/web-services and https://render.com/docs/disks.
