# Skillvaya — Owner and Customer User Guide

**Product:** Skillvaya · **Tagline:** Find your people. Get it done.  
**Release package:** Android APK and portable Windows EXE  
**Last updated:** 20 October 2026

## 1. The two-app design

Skillvaya has two distinct experiences:

- **Owner App:** the private workspace for the platform owner. It contains the Owner Control screen, payments/refunds overview, a website link, and website-sharing controls. The owner does not need to create a customer account or buy a provider plan to use the owner app on the local development PC.
- **Customer App:** the separate experience for customers and service providers. Registration, login, provider profiles, enquiries, plan selection and payment flows belong here. A provider's paid placement must not be activated just because they register or return from a payment page.

Owner Control is opened inside the Owner App and includes a Back button. The public deployment must have proper owner authentication; the local developer shortcut is not intended for internet exposure.

## 2. Open the apps on the development PC

Project folder: `C:\Users\user\Documents\Codex\Skillvaya`

- Windows installer: `downloads\Skillvaya.exe`
- Android installer: `downloads\Skillvaya.apk`
- Owner App local route: `http://127.0.0.1:8877/owner-app` when the local development service is running.
- Customer App local route: `http://127.0.0.1:8877/customer` when the local development service is running.
- Public-facing website preview: `http://127.0.0.1:8877/` when the local development service is running.

The URLs above are loopback addresses. They work on the PC running the service, not on another person's phone or computer. Do not advertise them as public links.

## 3. Website link and sharing

The Owner App has **Open Skillvaya website** and **Share website link** controls. The website also has **Share Skillvaya** and **Share website** buttons. Where supported, Share opens the device's native sharing sheet. Otherwise the app tries to copy the URL or shows it for manual copying.

**Important:** a link such as `http://127.0.0.1:8877/` is private to the local machine. Public sharing becomes useful only after the website is deployed to a real public HTTPS domain. Replace the local URL with that final domain in launch materials after deployment; do not invent or publish a domain before it exists.

## 4. Website downloads

On a hosted release website, the download button selects:

- Android: `/downloads/Skillvaya.apk`
- Windows: `/downloads/Skillvaya.exe`

The APK is a signed release package. Android may ask the user to permit installation from the browser/file source. Users should install only packages delivered from the official Skillvaya HTTPS domain. Windows may show an unknown-publisher warning because the EXE is not Authenticode-signed. Do not advise users to bypass warnings unless the release publisher and file integrity have been independently verified.

## 5. Owner Control overview

The control screen includes account email addresses, listings, payment requests, reports/complaints, alerts/notifications, usage metrics, owner-email settings, compose email, and the Skillvaya in-app alert inbox. Email composition is inside the app UI, but actual email delivery requires SMTP credentials on the server. The in-app alert inbox is not a live Gmail inbox; live Gmail receiving requires OAuth and mailbox synchronization.

## 6. Plans and South African payments

Provider plans are displayed in South African rand (ZAR). The current code defines Local R105/month, Priority R210/month, Business Plus R500/month, and Business Spotlight R1,000/month; yearly billing is calculated at 11 months' price. Confirm these prices and commercial terms before public launch.

PayFast integration code creates signed checkout fields, accepts ITN notifications, checks signatures, merchant ID, reference and amount, and calls PayFast's server-side validation endpoint. Paid placement should activate only after a verified `COMPLETE` notification. Refund controls are restricted to confirmed transactions and depend on PayFast API credentials.

**Live payment status:** not yet verified. A real public HTTPS callback, verified merchant credentials, sandbox checkout/ITN testing and refund testing are release prerequisites. Keep the service in sandbox until these checks pass. Never store merchant secrets in source control, website JavaScript, APK assets or this guide.

## 7. Data and privacy

The current standalone builds use device-local SQLite databases. Data entered on one device is not automatically synchronized to other users' devices. Do not promise a shared marketplace until the backend is deployed and tested. Production deployment needs a persistent database/disk, backups, restore testing, logging, monitoring, access controls, session expiry/revocation, rate limiting and privacy/data-retention rules. The owner email address currently shown in settings is `skillvaya@gmail.com`; sending/receiving has not been fully configured or verified.

## 8. Troubleshooting

- **Website link opens only on this PC:** hosting is not public yet, or you are using the local development URL.
- **Download returns 404 on a hosted site:** confirm both installer files are included in the deployment artifact and the host's file-size limits allow them.
- **Android install is blocked:** verify the APK came from the official domain and check Android's install-permission settings. The app has not yet been confirmed on a physical test device.
- **Windows warning:** the EXE is not Authenticode-signed.
- **Email says not sent:** configure server-side SMTP and verify a test message; a saved sender address alone does not enable sending.
- **PayFast stays pending:** inspect the public callback URL, merchant settings, server logs and ITN delivery. Browser return pages never prove payment.
- **Customer cannot see another device's records:** shared production database synchronization has not been deployed.

## 9. Support and release discipline

Use the deployment checklist and `DEPLOYMENT_READINESS.md` before a public release. Test on a clean Android device, a separate Windows PC, a customer account, and an owner account. Do not claim a public launch, successful real payment/refund, live email, or cross-device synchronization until each has been verified end to end.
