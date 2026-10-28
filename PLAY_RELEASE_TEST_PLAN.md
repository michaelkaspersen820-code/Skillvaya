# SkillVaya Play Release Test Plan — source 1.3.3 / versionCode 34

## Verified in the isolated latest-version clone
- [x] Clone is based on `feature/account-deletion-staging-20261028`, version 1.3.3 / code 34.
- [x] Target and compile SDK are 36.
- [x] Hosted Gradle URL must use HTTPS.
- [x] Hosted builds set `usesCleartextTraffic=false`; local/offline builds retain cleartext only for the local server.
- [x] Staging bundle script blocks the known production host, preflights key routes, and requires explicit confirmation of database isolation.
- [x] Gradle release manifest-processing task passed with an HTTPS URL.
- [x] `app.py` syntax compilation passed.
- [x] Seven account-deletion workflow checks passed against a temporary database, including Play token and password-reset token cleanup.
- [x] Ten static Google Play Billing guard tests passed.
- [x] Four password-recovery tests passed; owner access-control, 35 growth-feature and 17 Job Hub checks passed.
- [x] Owner terms and admin API smoke checks passed against a temporary local database.
- [x] Final Android Java compilation passed after billing replacement/polling changes.
- [x] Public live GET checks passed for `/customer-app`, `/privacy`, and `/account-deletion`.
- [x] No AAB has been built from this latest clone; no install, push, deployment, production migration, payment change or Play Console submission was performed.

## Not yet verified — release blockers
- [ ] Verify the staging startup guard reports the expected isolated database before any purchase/deletion tests.
- [ ] Create/confirm recurring auto-renewing Google Play subscription products and monthly/annual base plans.
- [ ] Configure Google Android Publisher API service-account credentials on staging. Pub/Sub/RTDN is optional; no-Pub/Sub lifecycle polling is implemented.
- [ ] Connect the staging service to `skillvaya_deletion_staging_db`; the latest deployment failed safely because `DATABASE_URL` is missing; Render reports no open port and the staging URL timed out.
- [ ] Test successful, pending, invalid, duplicate and wrong-user purchases with Play license testers in isolated staging.
- [ ] Verify renewals, cancellation, expiry, refund/revocation, restore, tier replacement and cross-device handling.
- [ ] Verify deletion request capture, owner queue, completion and email acknowledgement in isolated staging.
- [ ] Review data inventory and complete evidence-based Data safety answers.
- [ ] Review privacy policy and account-deletion page content/fulfilment process.
- [ ] Finalize listing description, category, contact/support details, icon and feature graphic.
- [ ] Capture at least two valid screenshots from the exact tested 1.3.3 candidate; the older screenshot drafts were intentionally not copied.
- [ ] Run physical Android device regression: signup/sign-in, browse/search, provider pages, free customer journey, provider onboarding, four plans, owner exemption, messages, attachments, camera/microphone/video, account deletion, settings, offline/error paths.
- [ ] Check signing certificate and versionCode against any prior Play upload before final AAB build.
- [ ] Upload to internal testing, review Play Console warnings and crash/ANR reports, complete any account-specific closed testing, and only then request production access.

## Billing model
Use Google Play Billing for eligible digital provider plans in the Play app. Keep PayPal on the website. Use recurring auto-renewing monthly and annual subscriptions, with cancellation through Google Play. Do not grant entitlements from a client-only success callback.

## Safety
Do not run destructive deletion tests or payment tests against live production data. Do not replace the existing APK, deploy to production, change live PayPal settings, or submit a release until the candidate has passed the checks above and the user explicitly approves the release.
