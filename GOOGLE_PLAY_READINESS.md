# SkillVaya Google Play readiness — 28 October 2026

## Current source baseline
- Working directory: `C:\Users\user\Documents\Codex\Skillvaya-Play-Prep-Latest-20261028`
- Source branch: `feature/account-deletion-staging-20261028`
- Package ID: `za.co.skillvaya.app`
- Current source version: **1.3.3 / versionCode 34**
- Target / compile SDK: **36 (Android 16)**
- Previous local candidate 1.2.9 / versionCode 30 is stale relative to this branch and must not be uploaded.
- No new AAB has been built from this current-version preparation clone. No app was installed over the existing phone app.

## Changes made in this isolated preparation clone
- Gradle rejects hosted URLs that are not HTTPS.
- Manifest cleartext traffic is enabled only for local/offline mode; hosted builds use `usesCleartextTraffic=false`.
- `prepare-play-bundle.ps1` requires an explicit HTTPS staging URL, refuses the production host, checks essential public routes, and requires explicit confirmation that staging uses a separate non-production database before building.
- The billing implementation was committed and pushed to the staging branch as `2b1fb2db427a816e99f616f4dfa6b69e4dbd09db`. A staging-only expected-database environment guard was configured. The billing commit has not yet been observed in a successful Render deployment.
- No production deployment, production database migration, live payment change, Play Console submission, or public APK replacement was performed.

## Public endpoint checks on 28 October 2026
GET requests returned HTTP 200 for:
- `https://skillvaya.onrender.com/customer-app`
- `https://skillvaya.onrender.com/privacy`
- `https://skillvaya.onrender.com/account-deletion`
- `https://skillvaya-deletion-staging.onrender.com/customer-app`
- `https://skillvaya-deletion-staging.onrender.com/privacy`
- `https://skillvaya-deletion-staging.onrender.com/account-deletion`

The live customer-app HTML contains the account-deletion request text; the public deletion page includes a submit-request UI and an email fallback. Page availability is verified; authenticated request capture, owner processing, completion acknowledgement and legal-retention handling still require an isolated end-to-end test.

**Database isolation is not confirmed for the Render staging service. Do not perform destructive account-deletion or payment tests there until the service's database is confirmed to be separate from production.**

## Play release blockers
1. **Native Google Play Billing has been added locally.** The Android build uses Billing Library 9.1.0 and routes native provider checkout through Play Billing. Backend purchase verification and an authenticated Pub/Sub lifecycle endpoint have been added. Real purchases have not been tested; Play Console products, API credentials, Pub/Sub and isolated staging verification are still required.
2. **Play Console product setup is pending.** The selected model is recurring auto-renewing subscriptions with cancellation through Google Play. Product IDs, base plans and prices are documented in `PLAY_BILLING_SETUP.md`; existing IDs must be checked before creation; product IDs must be checked in Console before creation.
3. **Data safety is not final.** `DATA_SAFETY_WORKSHEET.md` is an evidence checklist, not a completed Play Console declaration.
4. **Deletion workflow needs staging verification.** The public URLs respond, but test request/queue/completion/email using a confirmed isolated database and physical device.
5. **Store assets are drafts.** The copied 512x512 icon and 1024x500 feature graphic need final review; screenshots must be captured from the tested 1.3.3 candidate, not copied from the older version.
6. **Physical-device regression is incomplete.** Test signup/login, customer browse/contact, provider profile, each tier, messaging/attachments, camera/microphone/video, account deletion, owner controls, offline/error paths and all existing features.
7. **Play Console declarations and test track are pending.** Complete privacy/data safety, account deletion, content rating, target audience, ads, app access/reviewer instructions, subscription disclosures, store listing, internal testing, review of warnings/crashes/ANRs and any account-specific closed-testing requirement.

## Official policy references
- Target API: https://support.google.com/googleplay/android-developer/answer/11926878
- Payments policy: https://support.google.com/googleplay/android-developer/answer/10281818
- Account deletion: https://support.google.com/googleplay/android-developer/answer/13327111
- Play Billing integration: https://developer.android.com/google/play/billing
- Subscription setup: https://support.google.com/googleplay/android-developer/answer/140504

## Release decision
**Not ready to upload.** The current source baseline is 1.3.3 / code 34, hosted-build safety guards are in place, and public deletion/privacy page reachability has been checked. Do not submit until Play Billing products and credentials, staging isolation, Data Safety and device purchase tests are complete.
