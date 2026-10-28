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
- The candidate branch now includes production commit `e8efbad` (password recovery and owner deletion queue) plus prepaid subscription replacement, no-Pub/Sub lifecycle polling and deletion-token cleanup. Candidate commit `800bbf5` is pushed to `feature/account-deletion-staging-20261028`; the production branch remains unchanged.
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

**Database isolation is not confirmed for the Render staging service. Do not perform destructive account-deletion or payment tests there until the service's database is confirmed to be separate from production.** The separate database resource exists, but the staging service is not yet connected because `DATABASE_URL` is absent.

## Play release blockers
Play Console products, API credentials and isolated staging verification are still required; Pub/Sub is not a release prerequisite for the polling design.
The selected model is prepaid monthly and annual subscriptions with no automatic renewal; users must approve a new purchase to extend access.
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
The current source baseline is 1.3.3 / code 34; local regression tests and Android Java compilation pass. A production-targeted signed APK and AAB have been built, and their signing certificate matches the existing downloaded production APK. The latest staging deploy failed safely because `DATABASE_URL` is missing, so the database guard prevented the new code from starting. Render currently reports no open port and the staging URL timed out; staging is unavailable until the database is connected. Production was not changed.
