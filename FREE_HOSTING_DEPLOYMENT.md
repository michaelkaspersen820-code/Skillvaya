# Skillvaya — zero-monthly-cost staging deployment

This branch prepares Skillvaya to run on a free Render web service with a separate Neon PostgreSQL database. The app continues to use SQLite for local development when `DATABASE_URL` is absent.

## Important status

- Launch / and /customer always show sign-in. The marketing page is /website, the customer/provider workspace is /customer-app, and installed web apps start at /login.

- Launch / and /customer always show sign-in. The marketing page is /website, the customer/provider workspace is /customer-app, and installed web apps start at /login.

- The code changes are prepared on branch `free-hosting-postgres`; they are not yet merged to `main`.
- Do not accept real customers or payments until the branch's CI passes, the hosted service starts successfully, database persistence is verified across a restart, and PayPal Sandbox order/capture/refund paths are verified.
- Free Render services can sleep when idle. The first visit after sleep may be slow.
- No paid Render service or database is created by this configuration. Check provider terms and usage limits before relying on a free tier for a business.

## Set up the free database

1. Create a free project in Neon at https://neon.tech/ and create/select its PostgreSQL database.
2. Copy the PostgreSQL connection string from Neon's **Connect** panel. Keep it private; it is a password-bearing secret. Prefer the pooled connection string if Neon offers it for the project.
3. Do not commit the connection string into GitHub, source files, screenshots, or this repository.

## Deploy on Render's free web service

1. In Render, create a new Blueprint deployment from `michaelkaspersen820-code/Skillvaya` and select branch `free-hosting-postgres` for staging.
2. Review the Blueprint before applying it. It should select the free web-service plan, install `requirements.txt`, and not attach a paid persistent disk.
3. Add the following environment variables in the Render service dashboard:
   - `DATABASE_URL`: Neon connection string
   - `SKILLVAYA_PUBLIC_URL`: the exact public HTTPS Render URL
   - `SKILLVAYA_OWNER_EMAIL`: an email address controlled by the owner
   - `SKILLVAYA_OWNER_PASSWORD`: a unique random password of at least 14 characters
   - `SKILLVAYA_PAYPAL_MODE`: keep `sandbox` for now
   - `SKILLVAYA_PAYPAL_CLIENT_ID` and `SKILLVAYA_PAYPAL_CLIENT_SECRET`: PayPal Sandbox app credentials; keep them on the server and never commit them.
4. Deploy and inspect logs. A healthy `/healthz` response alone does not prove database writes or payment callbacks work.
5. Test registration, login, listing submission, notifications, and admin actions. Restart/redeploy the service and confirm the same records remain in PostgreSQL.
6. Keep PayPal in Sandbox. Verify OAuth credentials, create an order, approve it using a Sandbox buyer, capture it, and verify the matching ZAR amount/reference activates the plan. Test a partial refund before any live release.

## Migration and rollback

Local SQLite data is not automatically copied to Neon. Before switching an existing live database, export and verify it, then migrate it deliberately. For staging, use test accounts only. To roll back to SQLite locally, unset `DATABASE_URL`; never unset it on the hosted service after customer data has been written to PostgreSQL.

## Still required before a public launch

- Passing automated CI and hosted end-to-end checks
- Database backup/export and restore rehearsal
- Session expiry/revocation, CSRF, rate-limit, logging, and privacy review
- Verified email delivery
- PayPal Sandbox buyer-approved checkout, capture, partial/full refund, and replay/idempotency tests before enabling live credentials
- South African legal review of terms/privacy wording
- Separate-device onboarding and persistence tests
