# Google Play Billing setup — SkillVaya

Isolated candidate: version 1.3.3 / versionCode 34. No production deployment was performed.

## Added locally
- Google Play Billing Library 9.1.0 dependency.
- Native Android bridge to query subscription products, launch the Google Play purchase flow, restore purchases and submit purchase tokens to the backend.
- Native provider checkout routes to Google Play Billing. Website checkout remains PayPal/bank transfer.
- Backend endpoint `POST /api/google-play/verify` authenticates the provider, verifies the token through Google Play Developer API, checks state/expiry/product, prevents cross-account token reuse, updates existing SkillVaya entitlements; the Android client acknowledges a purchase only after the server confirms verification.
- Current source targets API 36; version incremented to 1.3.3/code 34.

## Products expected in Play Console
Create recurring auto-renewing subscriptions with the exact IDs below after checking that they do not already exist.

| Product ID | Tier | Monthly | Annual (12 months for 11 payments) |
|---|---|---:|---:|
| `skillvaya_local` | Local | R105 | R1,155 |
| `skillvaya_priority` | Priority | R210 | R2,310 |
| `skillvaya_business_plus` | Business Plus | R500 | R5,500 |
| `skillvaya_business_spotlight` | Business Spotlight | R1,000 | R11,000 |

Base plan IDs expected by the app: `monthly` (P1M) and `annual` (P1Y). Because the existing Skillvaya UI offers monthly and annual billing, create both base plans before release unless the annual option is deliberately removed from the Play build. Configure ZAR prices and South Africa availability.

## External setup still required
1. Create/confirm the products and base plans in Play Console.
2. Enable Google Play Android Developer API in the Google Cloud project.
3. Create a service account, grant the minimum required Play Console permissions, and store its JSON key only as a secret environment variable on the isolated Render staging service.
4. Set `GOOGLE_PLAY_PACKAGE_NAME=za.co.skillvaya.app` and `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` on staging only. Never place credentials in the app or repository.
5. Positively confirm that the staging database is separate from production before testing.
6. Configure Real-time Developer Notifications or a server reconciliation job for renewals, cancellations, refunds and revocations.
7. Run license-tester purchase tests from an internal-track Play-installed build, including restore, cancellation, expiry, refund, pending payment, wrong-account token and duplicate-token cases.

The billing code has not yet been deployed or tested against real Play purchases. The candidate is not ready to submit until these gates pass.
