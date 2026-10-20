# Skillvaya — Release and Deployment Readiness

## Current verified state
- Python syntax compilation passes for `app.py` and `qa_one_go.py`.
- Isolated end-to-end QA passed 19/19 checks on 2026-10-20 (latest run after deployment owner-bootstrap changes).
- Registration requires explicit Terms acceptance on the server.
- Passwords are stored using PBKDF2-HMAC-SHA256; legacy SHA-256 hashes are upgraded after successful login.
- PayFast checkout creation, signed checkout fields, ITN signature validation, server-side PayFast notification validation, duplicate-notification handling, amount/reference matching, and ITN-only subscription activation are implemented in the local code. Sandbox checkout construction and pending-until-verified behavior passed isolated tests. A real PayFast ITN and refund have not yet been exercised because this installation has no public HTTPS callback URL or live merchant configuration.
- PayFast refund API query/create logic and owner-side partial/full refund controls are implemented for verified PayFast transactions; no refund is claimed or sent until the merchant API confirms success.
- Customer listings are not seeded with fabricated sample providers.
- Customer app and Owner Control are separate screens. The no-login developer shortcut is restricted to loopback; public admin access requires an authenticated admin session.
- Added a production startup gate: when the hosting platform supplies `PORT`, startup requires `SKILLVAYA_OWNER_EMAIL` and a unique `SKILLVAYA_OWNER_PASSWORD` of at least 14 characters. The owner account is bootstrapped from those host secrets.
- Created a local Git repository with two commits and deployment files excluded from secret/data backups. It has not been pushed: the connected GitHub account currently exposes no repositories, and no remote repository is configured.
- Database backups are present in the project folder.

## Not production-ready yet
1. **Payments:** The PayFast integration is present in code, but the running local installation is not connected to a public HTTPS callback or live merchant account. Live money movement remains disabled until credentials and deployment configuration are supplied and sandbox ITN/refund tests pass.
2. **Email:** Owner email address is configured as skillvaya@gmail.com, but SMTP is not configured and actual send/receive has not been verified. See EMAIL_CONFIGURATION.md.
3. **Public hosting:** Local mode still binds to `127.0.0.1:8877`. Managed hosting mode binds to the platform's `PORT` and `0.0.0.0`, but no remote Git repository or hosting service is connected. Public startup fails closed without owner credentials; session expiry/revocation, rate limiting, logging, CSRF review, and security validation remain release gates.
4. **SV icon:** Original SV icon generation was unavailable during this pass. Do not treat the current icon as the requested new original branding.
5. **Legal review:** Terms acceptance is technically enforced, but the legal wording should be reviewed by a South African legal professional before public launch.
6. **Operational safeguards:** Add production logging, monitoring, database backup/restore drills, session expiry/revocation, rate limiting, and privacy/data-retention policy before launch.

## Recommended release gate
Do not publish publicly until owner bootstrap and authentication are verified on the hosting platform, payment gateway callbacks are verified in sandbox, email send/receive tests pass, production security review passes, a domain and HTTPS are configured, and a separate-device customer onboarding test succeeds.

## Local run
Run `Launch-Skillvaya.ps1` for the customer app and `Launch-Owner-Control.ps1` for the separate local owner console. Both use the local service at `http://127.0.0.1:8877`.
