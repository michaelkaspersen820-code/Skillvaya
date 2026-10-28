# SkillVaya Play implementation status — 28 October 2026

## Isolated candidate
- Folder: `C:\Users\user\Documents\Codex\Skillvaya-Play-Prep-Latest-20261028`
- Branch: `feature/account-deletion-staging-20261028`
- Commit pushed: `2b1fb2d` — Play Billing implementation and release guards
- Package: `za.co.skillvaya.app`
- Candidate source: **1.3.3 / versionCode 34**
- Target and compile SDK: **36**
- No production deployment, production database migration, live payment change, phone-app replacement or Play Console submission occurred.

## Implemented locally and pushed to the staging branch
- Added Google Play Billing Library 9.1.0 and a native Android bridge for subscription product lookup, purchase launch, restoration and backend verification.
- Native provider checkout now uses Google Play Billing. Website checkout remains on the existing PayPal/bank-transfer flow.
- Added `POST /api/google-play/verify` for Android Publisher API verification, product/state/expiry validation, account binding, duplicate-token protection, entitlement update and idempotent purchase recording.
- Android client acknowledges purchases only after server verification succeeds.
- Added authenticated `POST /api/google-play/rtdn` for lifecycle reconciliation.
- Added a visible Restore purchases action and a Google Play manage/cancel link.
- Fixed a billing account-ID encoding mismatch and prevented annual checkout from silently falling back to the monthly base plan.
- Upgraded Android Gradle Plugin to 8.9.3 and Gradle to 8.11.1.
- Hosted builds require HTTPS; hosted WebView cleartext traffic is disabled.
- Added a fail-closed database guard. If `SKILLVAYA_EXPECTED_DATABASE` is configured, `init()` verifies `current_database()` before schema initialization and refuses to start if it differs.
- Configured the Render staging service with `SKILLVAYA_EXPECTED_DATABASE=skillvaya_deletion_staging_db`. This does not change production settings. The new source still needs to be observed starting successfully against that database before tests/building.

## Tests completed locally
- Python syntax compilation passed.
- Seven static Google Play Billing guard tests passed.
- Six account-deletion workflow tests passed against a temporary local test database.
- Android Java release compilation passed with SDK 36 and the updated Gradle toolchain.
- `git diff --check` passed before commit.
- Real Play purchase/lifecycle tests have not been run.

## Still required before release
1. Verify Render's staging deployment starts successfully and logs no database safety guard failure.
2. Verify the staging service really uses the separate `skillvaya_deletion_staging_db` before any account deletion or payment test.
3. In Play Console, check whether the four product IDs already exist; then create/activate the recurring monthly and annual base plans.
4. Enable Android Publisher API, create a service account, grant the minimum Play Console permissions and store the JSON key only in staging secrets.
5. Configure authenticated Pub/Sub Real-time Developer Notifications.
6. Upload a signed AAB to internal testing and run actual license-tester purchases: success, pending, restore, cancellation, renewal, grace period, expiry, refund/revocation, wrong-account token, duplicate token and second-device access.
7. Finish evidence-based Data Safety answers, account-deletion workflow test, store listing assets, physical-device regression and Play Console warnings/crash/ANR review.

## Important
The billing implementation is present in source and compile checks pass, but **Play Console products, Google API credentials, Pub/Sub and real purchase tests are not complete**. Do not submit this candidate to production until these gates pass.
