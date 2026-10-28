# Google Play Billing setup — SkillVaya

Isolated candidate: version 1.3.3 / versionCode 34. No production deployment was performed.

## Added locally
- Google Play Billing Library 9.1.0 dependency.
- Native Android bridge to query subscription products, launch the Google Play purchase flow, restore purchases and submit purchase tokens to the backend.
- Native provider checkout routes to Google Play Billing. Website checkout remains PayPal/bank transfer.
- Backend endpoint `POST /api/google-play/verify` authenticates the provider, verifies the token through Google Play Developer API, checks state/expiry/product, prevents cross-account token reuse, updates existing SkillVaya entitlements; the Android client acknowledges a purchase only after the server confirms verification.
- SkillVaya uses prepaid base plans only. These plans never renew automatically; a user must approve a separate purchase to extend access. Tier changes use Google Play's CHARGE_FULL_PRICE replacement mode, and multiple active subscriptions block a new checkout to reduce duplicate-charge risk.
- Lifecycle reconciliation uses the Android Publisher API on provider API requests (throttled to at most once per 10 minutes) and during the existing hourly expiry sweep. Google Cloud Pub/Sub is not required for this build.
- Current source targets API 36; version incremented to 1.3.3/code 34.

## Products expected in Play Console
Create prepaid Google Play subscriptions with the exact IDs below after checking that they do not already exist. Do not configure auto-renewing base plans.

| Product ID | Tier | Monthly | Annual (12 months for 11 payments) |
|---|---|---:|---:|
| `skillvaya_local` | Local | R105 | R1,155 |
| `skillvaya_priority` | Priority | R210 | R2,310 |
| `skillvaya_business_plus` | Business Plus | R500 | R5,500 |
| `skillvaya_business_spotlight` | Business Spotlight | R1,000 | R11,000 |

Base plan IDs expected by the app are monthly (P1M) and annual (P1Y). Configure both as prepaid, not auto-renewing, with ZAR prices and South Africa availability. Annual prepaid is one P1Y period priced at 11 monthly payments for 12 months of access.

## External setup still required
1. Create/confirm the products and base plans in Play Console.
2. Enable Google Play Android Developer API in the Google Cloud project.
3. Create a service account, grant the minimum required Play Console permissions, and store its JSON key only as a secret environment variable on the isolated Render staging service. A paid API key is not required for this service-account authentication flow.
4. Set `GOOGLE_PLAY_PACKAGE_NAME=za.co.skillvaya.app` and `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` on staging only. Never place credentials in the app or repository.
5. Connect the staging service to the separate `skillvaya_deletion_staging_db`. The current staging service is missing `DATABASE_URL`; the new deployment correctly fails closed until that connection is set.
6. No Pub/Sub setup is required for launch: subscription state is refreshed through the Android Publisher API on provider requests and the hourly expiry sweep. The authenticated RTDN endpoint remains an optional future optimization.
7. Run license-tester purchase tests from an internal-track Play-installed build, including first purchase, restore, prepaid tier replacement, a separate manual extension purchase, expiry, refund/revocation, pending payment, wrong-account token and duplicate-token cases. Confirm no auto-renewing plan is offered or accepted.

The billing code has not yet been deployed or tested against real Play purchases. The candidate is not ready to submit until these gates pass.


## Prepaid billing rule (important)

Create all monthly and annual base plans as prepaid, never auto-renewing. A new, explicitly approved purchase is required to extend paid access. The backend rejects an auto-renewing plan response and grants no access if a product is misconfigured. Prepaid plan replacement uses Google Play CHARGE_FULL_PRICE mode.
