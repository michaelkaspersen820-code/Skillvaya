# SkillVaya Play implementation status — 28 October 2026

## Isolated candidate
- Folder: `C:\Users\user\Documents\Codex\Skillvaya-Play-Prep-Latest-20261028`
- Branch: `feature/account-deletion-staging-20261028`
- Base billing commit previously pushed: `2b1fb2d` — Play Billing implementation and release guards. The local merge commit includes production commit `e8efbad` plus billing/data-deletion hardening; it is committed locally but not pushed yet.
- Package: `za.co.skillvaya.app`
- Candidate source: **1.3.3 / versionCode 34**
- Target and compile SDK: **36**
- No production deployment, production database migration, live payment change, phone-app replacement or Play Console submission occurred.

## Implemented in the isolated candidate (base billing commit pushed; latest parity merge/hardening remains local)
- Added Google Play Billing Library 9.1.0 and a native Android bridge for subscription product lookup, purchase launch, restoration and backend verification.
- Native provider checkout now uses Google Play Billing. Website checkout remains on the existing PayPal/bank-transfer flow.
- Added `POST /api/google-play/verify` for Android Publisher API verification, product/state/expiry validation, account binding, duplicate-token protection, entitlement update and idempotent purchase recording.
- Android client acknowledges purchases only after server verification succeeds.
- Added subscription replacement for tier changes, strict monthly/annual base-plan validation, linked-token retirement, and no-Pub/Sub lifecycle polling through Android Publisher API (10-minute throttle on provider requests plus hourly expiry reconciliation). The authenticated RTDN endpoint remains optional.
- Merged the latest production-branch password-recovery and owner account-deletion queue changes into the isolated candidate.
- Account deletion now removes stored Google Play purchase tokens and password-reset tokens, and warns users that Google Play billing must be canceled separately.
- Added a visible Restore purchases action and a Google Play manage/cancel link.
- Fixed a billing account-ID encoding mismatch and prevented annual checkout from silently falling back to the monthly base plan.
- Upgraded Android Gradle Plugin to 8.9.3 and Gradle to 8.11.1.
- Hosted builds require HTTPS; hosted WebView cleartext traffic is disabled.
- Added a fail-closed database guard. If `SKILLVAYA_EXPECTED_DATABASE` is configured, `init()` verifies `current_database()` before schema initialization and refuses to start if it differs.
- Configured the Render staging service with `SKILLVAYA_EXPECTED_DATABASE=skillvaya_deletion_staging_db`. This does not change production settings. The new source still needs to be observed starting successfully against that database before tests/building.

## Tests completed locally
- Python syntax compilation passed.
- Ten static Google Play Billing guard tests passed.
- Seven account-deletion workflow checks passed against a temporary local test database, including deletion of Play purchase tokens and password-reset tokens.
- Four password-recovery tests passed.
- Owner access-control regression passed.
- Thirty-five provider-growth checks and seventeen Job Hub checks passed.
- Owner terms/public page and five owner API smoke checks passed against a temporary local SQLite database.
- Android release Java compilation passed with SDK 36 and the updated Gradle toolchain.
- `git diff --check` passed.
- Real Play purchase/lifecycle tests have not been run.

## Still required before release
1. Connect the staging Render service to `skillvaya_deletion_staging_db`. The expected-database guard is configured, but `DATABASE_URL` is missing, so the latest staging deployment failed safely. Render currently reports no open port and the staging URL timed out; staging is unavailable until the database is connected.
2. Confirm the staging service starts against that separate database before any account deletion or payment test.
3. Sign in to Play Console, check whether the four product IDs already exist, then create/activate the recurring monthly and annual base plans.
4. Enable Android Publisher API, create a service account, grant minimum Play Console permissions and store the JSON key only in staging secrets. No paid API key or Pub/Sub setup is required for the current polling design.
5. Upload a signed AAB to internal testing and run actual license-tester purchases: success, pending, restore, tier replacement, cancellation, renewal, grace period, expiry, refund/revocation, wrong-account token, duplicate token and second-device access.
7. Finish evidence-based Data Safety answers, account-deletion workflow test, store listing assets, physical-device regression and Play Console warnings/crash/ANR review.

## Important
The current source has passed local regression and Android compile checks, but **Play Console products, Google API credentials, staging database connection, signed internal-test bundle and real purchase tests are not complete**. Pub/Sub is optional for this polling design. Do not submit this candidate to production until these gates pass.
