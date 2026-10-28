# SkillVaya Google Play Data Safety Worksheet

Status: investigation worksheet only. Do not submit guessed answers to Play Console.

## Observed in the copied Android manifest
- INTERNET permission.
- CAMERA permission.
- RECORD_AUDIO permission.
- MODIFY_AUDIO_SETTINGS permission.
- Camera and microphone hardware are marked optional.
- Android app is a WebView wrapper around the hosted SkillVaya service and asks for camera/microphone permissions for relevant features.

## Data categories that require a source-code/backend and provider audit
Confirm whether and how the app collects, transmits, shares, or stores each category:
- Account identifiers: name, email address, phone number, account role.
- Authentication: password hash, login/session token, account recovery information.
- User-generated content: provider descriptions, photos, profile picture, portfolio files, messages, job requests, quotes, complaints and reports.
- Contacts: user-entered contact details and provider business contact information. Do not assume device contacts are read; verify final code.
- Audio/video: microphone/camera streams for voice/video calls; confirm whether calls are peer-to-peer or relayed and whether media is recorded or stored.
- Files/media: user-selected profile/portfolio photos and chat attachments.
- Google Play purchase data: purchase token/order ID, product and base-plan identifiers, subscription state and expiry, prepaid-plan type, and non-auto-renew status.
- App activity and diagnostics: server request logs, timestamps, analytics events, IP address, device/browser user-agent and error logs.
- Messages and support content: private messages, account deletion requests, safety reports and support communications.

## Third-party processors to confirm
- Render hosting and logs.
- Neon PostgreSQL hosting.
- PayPal checkout and transaction records.
- Google Play Billing and the Google Play Android Publisher API (purchase verification, subscription state and expiry). The current design does not require Pub/Sub/RTDN.
- Any email/SMTP provider configured in the production environment.
- Browser/WebView services involved in voice recognition or video calling.
- Any analytics, monitoring, crash reporting or external SDK that is actually enabled.

## Questions that must be answered from evidence
1. Is each data category collected, shared, optional, required, or processed only on-device?
2. Is data encrypted in transit? Verify HTTPS for all production endpoints and no production mixed-content traffic.
3. Is data encrypted at rest? Confirm actual database/backup/provider settings instead of assuming.
4. What is the retention period for accounts, messages, attachments, payments, logs and deletion requests?
5. How can users request deletion, and what data may be retained for legal, payment, fraud-prevention or dispute reasons?
6. Is data used for advertising or shared with advertising networks? Confirm from code and provider settings.
7. Is the app designed for children? Confirm the target audience and Play Console declarations.
8. Does any external analytics or advertising SDK collect identifiers? Inspect final dependency tree and build.
9. Does video/voice calling record or store media? Document the real implementation.
10. Do the Data safety answers match the exact APK/AAB being submitted?

## Current blockers
- No evidence-based final Data safety answers yet.
- Live GET checks now return HTTP 200 for `/account-deletion` and `/privacy`, and the live customer-app HTML includes the account-deletion request text. The authenticated request API, owner queue, fulfilment and email acknowledgement still need end-to-end verification against a confirmed isolated test database.
- The isolated copy has a deletion-request workflow with owner-only completion and local tests, but that does not by itself prove the live backend's behaviour or legal-retention compliance.
- Native Play Billing, prepaid-only server verification and no-Pub/Sub polling lifecycle code have been added to the isolated candidate. Play Console products, Google Play service-account credentials on production, internal-track purchase tests, and final evidence-based Data Safety answers remain incomplete.

Official account-deletion policy: https://support.google.com/googleplay/android-developer/answer/13327111
