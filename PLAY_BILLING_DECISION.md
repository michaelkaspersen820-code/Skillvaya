# Google Play Billing — SkillVaya implementation and release gate

Status: Native billing, server verification, subscription replacement, and no-Pub/Sub lifecycle polling are implemented in the isolated source and compile. Play Console products, API credentials, staging database connection, internal-track build and real purchase tests remain outstanding. No live production checkout was changed.

## Why this matters
SkillVaya's provider tiers (Local R105, Priority R210, Business Plus R500, Business Spotlight R1,000) sell digital listing visibility and related in-app provider tools. Google Play generally requires Google Play Billing for digital goods/services purchased within a Play-distributed app unless a documented exception or approved program applies.

Official policy: https://support.google.com/googleplay/android-developer/answer/10281818

## Selected target architecture
Use Google Play Billing inside the Play-distributed Android app and keep the website's existing PayPal/bank-transfer checkout unchanged. The user has approved recurring auto-renewing subscriptions, with cancellation managed through Google Play. Existing PayPal subscriptions must not be migrated, canceled or double-charged.

## Product IDs and prices expected by the implementation
Create these only after checking whether each ID already exists. Product IDs cannot be renamed or reused after creation.

| Product ID | Tier | Monthly base plan | Annual base plan (12 months for 11 payments) |
|---|---|---:|---:|
| `skillvaya_local` | Local | R105 | R1,155 |
| `skillvaya_priority` | Priority | R210 | R2,310 |
| `skillvaya_business_plus` | Business Plus | R500 | R5,500 |
| `skillvaya_business_spotlight` | Business Spotlight | R1,000 | R11,000 |

Base plan IDs expected by the app: `monthly` (P1M) and `annual` (P1Y). Configure South Africa availability and ZAR prices. Ensure each base plan is auto-renewing. Use exact IDs; the Android UI intentionally does not fall back to a different billing period when a requested plan is missing.

## Implemented in the isolated copy
1. Added Google Play Billing Library 9.1.0 and a native Android bridge for product lookup, purchase launch, restore and server verification.
2. The Android provider checkout routes to Google Play Billing; website PayPal/bank-transfer checkout is unchanged.
3. Added `POST /api/google-play/verify`. It checks the purchase token using Android Publisher API, validates product/state/expiry and account binding, prevents cross-account token reuse, updates the existing entitlement, and records the Google Play purchase idempotently. The Android client acknowledges only after successful server verification.
4. Added subscription replacement for tier changes, strict monthly/annual base-plan validation, linked-token retirement, and server-side lifecycle polling through Android Publisher API. Provider API requests refresh stale state at most every 10 minutes; the existing hourly expiry sweep reconciles Play subscribers before suspending expired listings. No Pub/Sub service is required for this design. The authenticated RTDN endpoint is optional.
5. Added a Google Play manage/cancel link and explicit Google Play cancellation guidance on account deletion. Account deletion removes stored Play purchase tokens and password-reset tokens.
6. Added a fail-closed staging database guard. If `SKILLVAYA_EXPECTED_DATABASE` is set, the app checks `current_database()` before schema initialization and refuses to start if the name does not match.
7. API/Java compile checks and local regression suites pass. These are not substitutes for real Play purchase tests.

## Required external setup
1. In Play Console, inspect existing products, then create/activate the four subscriptions and both base plans for each.
2. Enable Google Play Android Developer API in the correct Google Cloud project.
3. Create a service account and grant only the required Play Console permissions (including View financial data for billing-related API access).
4. Store the service-account JSON as a secret on the isolated Render staging service only. Never place credentials in the APK, source code or chat.
5. No Pub/Sub setup is required. Confirm the Android Publisher service-account credentials and the polling lifecycle reconciliation are configured on staging.
6. Connect the Render staging service to `skillvaya_deletion_staging_db` and confirm the startup guard succeeds before any payment or destructive deletion test. The current `DATABASE_URL` is missing, so this gate is still blocked.
7. Add license testers, upload a signed bundle to the internal test track and test purchase, acknowledgement, restoration, tier replacement, cancellation, renewal, grace period, expiry, refund/revocation, wrong-account token and duplicate token.
8. Confirm that canceled subscriptions retain access until the paid expiry, and that expired/revoked subscriptions lose access. Verify provider plan changes and existing PayPal users are not double-charged.
9. Do not release until Data Safety, account deletion, store listing, physical-device regression and Play Console warnings are resolved.

## Do not do
- Do not change live website PayPal or deploy this source to the production service.
- Do not run payment or account-deletion tests against production data.
- Do not submit the AAB merely because it compiles.
