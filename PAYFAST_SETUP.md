# Skillvaya PayFast integration — configuration and release gate

## Implemented in app.py
- ZAR checkout form generation for monthly/yearly provider plans.
- PayFast signature generation for checkout fields.
- `POST /api/payfast/itn` receives form-encoded ITNs, checks signature, merchant ID, payment reference, expected gross amount, and PayFast's server-side `/eng/query/validate` result.
- Duplicate verified ITNs are handled idempotently; the same reference with a different PayFast transaction ID is rejected.
- Only a validated `COMPLETE` ITN activates a paid listing/subscription. A browser return alone does not activate a plan.
- Owner payment records expose refund actions only for PayFast-confirmed transactions. Refunds query the available balance and then submit a partial/full refund through PayFast's Refunds API; the app records the outcome only after PayFast confirms acceptance.
- Manual owner payment verification is disabled to prevent bypassing gateway verification.

## Required server environment
Set these on the server process (never in browser JavaScript):

- `SKILLVAYA_PAYFAST_MODE=sandbox` for testing, or `live` only after release approval.
- `SKILLVAYA_PAYFAST_MERCHANT_ID` — merchant ID from the selected PayFast account.
- `SKILLVAYA_PAYFAST_MERCHANT_KEY` — merchant key from the selected PayFast account.
- `SKILLVAYA_PAYFAST_PASSPHRASE` — passphrase configured in that PayFast account.
- `SKILLVAYA_PUBLIC_URL=https://your-real-domain` — public HTTPS base URL reachable by PayFast, without a trailing slash.

For sandbox only, the code uses PayFast's published sandbox test credentials when merchant ID/key/passphrase environment variables are absent. Do not use those values for live transactions. Live mode has no hard-coded live credentials.

## Required verification before live money
1. Deploy the app behind a proper production web server with a real HTTPS certificate and a stable public URL. The current local server binds to `127.0.0.1:8877`; PayFast cannot reach it directly.
2. Set sandbox environment variables and public HTTPS URL, then make a sandbox checkout and confirm the ITN reaches `/api/payfast/itn`.
3. Verify successful payment activates the correct provider listing, amount mismatch and bad signatures are rejected, cancelled payments stay inactive, and duplicate ITNs do not extend subscriptions twice.
4. Test a sandbox refund query and refund request, including a partial refund and a duplicate/retry scenario.
5. Switch to live only after those checks, with the real merchant credentials, owner access security, backups, logging, monitoring, rate limits, and legal/privacy review completed.

## Current honest status
The code compiles; isolated tests verified sandbox checkout field generation, expected amount, signature, public callback URL construction, and that the payment stays pending before verified notification. A real PayFast ITN, API refund, or live transaction has **not** been verified on this local PC because it does not have a public HTTPS callback or the owner's actual merchant credentials. No real payment or refund has been sent by this implementation yet.
