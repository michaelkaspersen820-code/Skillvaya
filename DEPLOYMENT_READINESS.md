# Skillvaya â€” Release and Deployment Readiness

## Current verified state
- Python syntax compilation passes for `app.py` and `qa_one_go.py`.
- Isolated end-to-end QA passed 19/19 checks on 2026-10-20 (latest run).
- Registration requires explicit Terms acceptance on the server.
- Passwords are stored using PBKDF2-HMAC-SHA256; legacy SHA-256 hashes are upgraded after successful login.
- PayFast checkout creation, signed checkout fields, ITN signature validation, server-side PayFast notification validation, duplicate-notification handling, amount/reference matching, and ITN-only subscription activation are implemented in the local code. Sandbox checkout construction and pending-until-verified behavior passed isolated tests. Dedicated PayFast checkout verification also passed for sandbox field generation, amount, public HTTPS ITN URL construction, signature, and pending-until-verified behavior. A real PayFast ITN and refund have not yet been exercised because this installation has no public HTTPS callback URL or live merchant configuration.
- PayFast refund API query/create logic and owner-side partial/full refund controls are implemented for verified PayFast transactions; no refund is claimed or sent until the merchant API confirms success.
- Customer listings are not seeded with fabricated sample providers.
- Customer app and Owner Control are separate screens; Owner Control is loopback-only.
- Database backups are present in the project folder.

## Not production-ready yet
1. **Payments:** The PayFast integration is present in code, but the running local installation is not connected to a public HTTPS callback or live merchant account. Live money movement remains disabled until credentials and deployment configuration are supplied and sandbox ITN/refund tests pass.
2. **Email:** Owner email address is configured as skillvaya@gmail.com, but SMTP is not configured and actual send/receive has not been verified. See EMAIL_CONFIGURATION.md.
3. **Public hosting:** The server intentionally binds to 127.0.0.1:8877. It is not a public website. Do not change it to 0.0.0.0 or publish it directly; local owner-control bypasses depend on loopback and a production deployment needs proper authentication, HTTPS, CSRF protections, rate limits, and a production server.
4. **SV icon:** Original SV icon generation was unavailable during this pass. Do not treat the current icon as the requested new original branding.
5. **Legal review:** Terms acceptance is technically enforced, but the legal wording should be reviewed by a South African legal professional before public launch.
6. **Operational safeguards:** Add production logging, monitoring, database backup/restore drills, session expiry/revocation, rate limiting, and privacy/data-retention policy before launch.

## Recommended release gate
Do not publish publicly until payment gateway callbacks are verified in sandbox and production, email send/receive tests pass, production security review passes, a domain and HTTPS are configured, and a separate-device customer onboarding test succeeds.

## Local run
Run `Launch-Skillvaya.ps1` for the customer app and `Launch-Owner-Control.ps1` for the separate local owner console. Both use the local service at `http://127.0.0.1:8877`.

