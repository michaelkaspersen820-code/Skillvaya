# SkillVaya Play implementation status — 28 October 2026

## Current isolated candidate
- Folder: `C:\Users\user\Documents\Codex\Skillvaya-Play-Prep-Latest-20261028`
- Branch: `feature/account-deletion-staging-20261028`
- Package: `za.co.skillvaya.app`
- Candidate source version: **1.3.3 / versionCode 34**
- Target and compile SDK: **36**
- No AAB has been built or submitted from this candidate. No production push/deploy or live payment change was performed.

## Implemented locally
- Added Google Play Billing Library 9.1.0.
- Added native Android billing bridge for subscription product lookup, purchase launch, purchase restore and secure server verification callback.
- Native provider plan checkout now opens Google Play Billing. Website checkout still uses its existing PayPal/bank-transfer flow.
- Added backend `POST /api/google-play/verify`: verifies the token with Android Publisher API, checks product/state/expiry, checks account linkage and duplicate-token ownership, verifies before granting access and acknowledges the purchase on the Android client after successful verification, and updates the existing subscription entitlement to the verified expiry.
- Added authenticated Pub/Sub endpoint `POST /api/google-play/rtdn` to reconcile known subscriptions against Google Play and suspend access on expiry/revocation. It requires audience, service-account identity and Play API credentials to be configured.
- Added a manage/cancel link to Google Play subscriptions after verification.
- Upgraded Android Gradle Plugin to 8.9.3 and Gradle wrapper to 8.11.1, both compatible with API 36; this removes the previous AGP 8.7/API 36 compatibility warning.
- Hosted builds still require HTTPS and disable cleartext traffic.
- Python syntax compilation passed.
- Added seven static billing guard tests; all seven pass.
- Existing six account-deletion flow tests pass.
- Final Gradle Java compilation passed after the account-ID hash and exact base-plan-selection fixes.

## Still required before the billing flow is usable
1. Create/confirm the four Play Console subscription products and base plans documented in `PLAY_BILLING_SETUP.md`.
2. Enable Android Publisher API, create a service account and grant it minimum Play Console permissions.
3. Set service-account credentials and Pub/Sub authentication settings as secrets on the isolated Render staging service only.
4. Positively confirm the staging database is separate from production.
5. Deploy these backend changes to staging only and verify route behavior.
6. Configure a Pub/Sub topic and authenticated push subscription to `/api/google-play/rtdn`.
7. Run real Play license-tester purchases from an internal-track-installed build: success, pending, restore, wrong-account token, duplicate token, cancellation, renewal, expiry, refund/revocation and second-device access.
8. Ensure existing PayPal subscribers are not double-charged or automatically migrated; website PayPal remains unchanged.
9. Finish Data Safety answers, account-deletion workflow test, screenshots, store listing, physical-device regression and internal test review.

## Important limitation
The billing integration is now present in the isolated source, but **Play Console products, API credentials, Pub/Sub configuration and real purchase tests are not complete**. Do not submit this candidate yet. No live Render deployment, live PayPal change, production database migration, phone-app replacement or Play Console submission occurred.
