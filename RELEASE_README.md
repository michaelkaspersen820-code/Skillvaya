# Skillvaya local preview package

This is a **local development preview**, not a production-ready public server package.

## Files
- `app.py` — application server and customer/owner interfaces.
- `run_local.py` — local startup entry point.
- `Launch-Skillvaya.ps1` — customer app launcher.
- `Launch-Owner-Control.ps1` — separate owner console launcher.
- `qa_one_go.py` — isolated end-to-end QA checks.
- `DEPLOYMENT_READINESS.md` — verified status and release blockers.
- `EMAIL_CONFIGURATION.md` — email setup and limitations.

## Run locally
Requires Python 3.12+ on Windows. Extract the archive, open PowerShell in the extracted folder, and run `python run_local.py`. The launchers open the local service at `http://127.0.0.1:8877`.

Do not expose this server directly to the internet. The owner controls are designed for loopback-only development. No customer database, account records, secrets, or backup databases are included in this archive.

## Payment and email limitations
Payment requests are manual-verification only; there is no live payment provider or automatic payment callback. SMTP has not been configured, and inbound email is not embedded in this app. See the readiness and email configuration documents before any public launch.
