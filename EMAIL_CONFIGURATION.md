# Skillvaya email setup

The app currently supports SMTP outbound email when configured through server environment variables. The owner destination is `skillvaya@gmail.com`. SMTP is not configured or verified in the current environment. The Owner Control Gmail link opens Gmail in the browser; it is not an embedded inbox.

## Gmail requirements
- Use a dedicated Google account or app password; never paste the normal Google password into the app.
- If Google 2-Step Verification is enabled, create an App Password if the account is eligible. If it is not enabled, configure account security first.
- Do not commit credentials to source files, database rows, browser JavaScript, or a release ZIP.

## Environment variable names
- `SKILLVAYA_SMTP_HOST` — usually `smtp.gmail.com`
- `SKILLVAYA_SMTP_PORT` — usually `587` for STARTTLS
- `SKILLVAYA_SMTP_USER` — full sender email address
- `SKILLVAYA_SMTP_PASSWORD` — app password or approved SMTP credential
- `SKILLVAYA_SMTP_FROM` — verified sender address

The app must be restarted after configuring variables so its Python process receives them. Then open Owner Control → Owner email → Send test email and confirm the message arrives. Until this succeeds, email notifications are stored in the local Alerts list but are not delivered.

## Receiving mail
Inbound email is not yet integrated into the app. The Gmail inbox button opens Gmail in the browser. An embedded inbox requires a secure OAuth/IMAP integration and must be separately configured and tested; it is not claimed as complete in this release.
