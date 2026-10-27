# Skillvaya 1.3.2 — 28 October 2026

- Added an account-deletion request option in the signed-in customer profile.
- Added the public HTTPS account-deletion information/request page.
- Added an owner-only pending request queue and irreversible completion action with explicit confirmation.
- Completion deletes associated account data transactionally, protects owner/admin accounts, minimizes direct identifiers in retained payment records where appropriate, and attempts an acknowledgement email after commit.
- Added request idempotency and safeguards against repeat completion.
- Android target API 36; versionCode 33.
- Production APK signed with the existing Skillvaya release signing certificate.

Release validation: local lifecycle tests and existing owner/auth, owner promotion, and Job Hub regression checks passed. Production health, deletion page, customer app, and owner app routes return HTTP 200; the owner queue correctly rejects unauthenticated access with HTTP 401. Completion email delivery still depends on SMTP configuration and has not been independently confirmed.
