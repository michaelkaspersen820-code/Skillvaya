# Skillvaya

Skillvaya is a South African service-provider marketplace. The hosted web service is the shared system of record for customer accounts, provider listings, enquiries, reports, subscriptions, and payment records. Native Android and Windows releases are configured at build time to open the same hosted service; local/offline mode is for development only.

## Deployment

This project includes `render.yaml` for a Render web service with a persistent disk at `/var/data`. The disk is required for the current SQLite database to survive restarts and redeploys. Keep a single service instance while using SQLite. All users connect to that one service and therefore share its marketplace database.

1. Push the sanitized source to a private GitHub repository.
2. Connect that repository to Render and create a Blueprint deployment from `render.yaml`.
3. Configure a strong unique `SKILLVAYA_OWNER_PASSWORD` (at least 14 characters) and `SKILLVAYA_OWNER_EMAIL` as secret environment values. Never put them in Git.
4. Set `SKILLVAYA_PUBLIC_URL` to the assigned HTTPS `onrender.com` URL, keep `SKILLVAYA_PAYFAST_MODE=sandbox`, and add the verified merchant sandbox settings as host secrets.
5. Verify owner login, signup, shared listing visibility from two separate devices, persistence after restart, PayFast sandbox ITN, email, backups, and restore before live launch.
6. Build the final Android APK with `SKILLVAYA_PUBLIC_URL` set to the hosted HTTPS URL. Build the Windows EXE with the same URL in `deployment.json`. Commit the final packages and redeploy so the public download buttons serve the shared-service builds.

## Costs and persistence

The included Blueprint uses Render's legacy `starter` web plan and a 1 GB persistent disk. Render's published pricing currently lists the small paid web instance at US$7/month and persistent disk storage at US$0.25/GB/month, so the planned baseline is approximately US$7.25/month before tax, bandwidth overages, a custom domain, or any other services. Check the final dashboard price before confirming paid service creation. A free web service cannot attach a persistent disk, so it is not appropriate for this SQLite-based live marketplace.

## Security and payments

Keep the owner password and all PayFast merchant values in hosting secret environment variables. Keep PayFast in sandbox until an actual public HTTPS ITN callback and sandbox refund test pass. Public release also requires verification of owner session controls, rate limiting, CSRF/security headers, email delivery, backup/restore, privacy policy and South African legal wording. Do not treat a successful local test as proof of live payment processing.
