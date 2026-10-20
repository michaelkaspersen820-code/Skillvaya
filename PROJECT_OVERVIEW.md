# Skillvaya — Project Overview and Architecture

## Product
Skillvaya is a South African services discovery marketplace for customers and providers, designed for mobile phones and PCs. Brand line: **Find your people. Get it done.** Currency: ZAR.

## Experiences
1. **Owner App** — private owner workspace, including Owner Control and payment/refund management, with website open/share actions. The local developer experience does not require a customer account or subscription. Public owner access must be protected by proper authentication.
2. **Customer App** — separate registration and sign-in flow for customers and service providers. Providers create profiles and may select paid visibility plans. Payment completion must be confirmed server-to-server, not inferred from browser redirects.
3. **Marketing website** — public-facing product explanation, service categories, provider plans, safety information and download buttons. Device-aware routes serve APK for Android and EXE for Windows.

## Technical layout
- `app.py`: Python standard-library HTTP server, HTML routes, account/business/report/payment APIs, SQLite persistence, PayFast handling, and owner/customer UI templates.
- `website.html`: marketing/download landing page with responsive design and share/install controls.
- `run_local.py`: local development entry point (default loopback port 8877).
- `android-native/`: Android Studio/Gradle wrapper project. The Android activity starts an embedded Python backend through Chaquopy and loads its local web UI in a WebView.
- `desktop_launcher.py`: packaged Windows entry point; starts a local service and opens an app-style Edge window when available.
- `downloads/Skillvaya.apk`: Android signed release artifact.
- `downloads/Skillvaya.exe`: Windows portable executable.
- `skillvaya.sqlite3`: local development data. Do not publish or commit live customer data.
- `PAYFAST_SETUP.md`, `EMAIL_CONFIGURATION.md`, `DEPLOYMENT_READINESS.md`, `DEPLOYMENT_STAGING_CHECKLIST.md`: payment, email and release configuration references.

## Current operation
Local app runs on `http://127.0.0.1:8877` on the development PC. Routes include `/` (marketing site), `/customer` (customer app), `/owner-app` (owner home), `/owner-control` (owner console) and `/downloads/Skillvaya.apk` / `/downloads/Skillvaya.exe` (installer files). Local URLs cannot be used by external customers.

The Android and Windows native builds currently run a local backend and local database. Cross-device sharing is not enabled by a production database/API deployment. The website is source code and local preview, not a live public domain.

## PayFast
ZAR checkout generation, signature verification, server-side ITN validation, pending/verified state handling, duplicate-notification protection and refund API paths exist in code. Live merchant verification, public HTTPS callback, real sandbox ITN/refund proof and production launch remain incomplete. See `PAYFAST_SETUP.md`.

## Email
Owner email defaults to `skillvaya@gmail.com`. Compose and local in-app alerts exist, but live outgoing SMTP and Gmail inbox sync have not been proven. See `EMAIL_CONFIGURATION.md`.

## Security and launch limitations
- Public hosting requires a unique owner password and owner identity supplied through host secrets.
- Do not expose the local no-login developer route publicly.
- Configure HTTPS, persistent storage, tested backups, secure sessions, CSRF protection, rate limiting, logging, monitoring and privacy controls.
- Review POPIA and marketplace terms with South African counsel.
- The Windows EXE is not Authenticode-signed; Windows may display an unknown-publisher warning.
- APK has not yet passed a physical-device smoke test.

## Documentation index
- `USER_GUIDE.md` — owner/customer workflow and troubleshooting.
- `RELEASE_CHECKLIST.md` — build verification and public launch gates.
- `PROJECT_OVERVIEW.md` — architecture and current boundaries.
- `NATIVE_BUILD_README.md` — local Android/Windows rebuild commands.
- `README_DEPLOYMENT.md` — deployment scaffold summary.
- `DEPLOYMENT_READINESS.md` and `DEPLOYMENT_STAGING_CHECKLIST.md` — security/production blockers.
- `PAYFAST_SETUP.md` — payment setup and verification.
- `EMAIL_CONFIGURATION.md` — email setup and verification.
