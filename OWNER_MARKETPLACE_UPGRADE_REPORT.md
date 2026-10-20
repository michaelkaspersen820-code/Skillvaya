# Skillvaya owner marketplace upgrade — work report

Date: 20 October 2026

## Implemented locally

- Added a persistent `owner_promotions` database table for owner-created business profiles, adverts, products/services and app promotions.
- Added owner-only API operations to create, list, pause, publish and remove owner promotions.
- Stores the owner fee exemption on each record (`owner_free=1`); these entries do not create customer subscription/payment records.
- Added **My Businesses & Promotions** to Owner Control and simplified the Owner App shell to Home, Owner Control and Customer App; removed duplicate top-level payments/promotions tabs.
- Replaced the long row of repeated Owner Control buttons with one grouped work-area selector for Marketplace, Platform Operations, Payments, and Communications & Settings.
- Added a public read-only API for active owner promotions and a public website section that renders the active entries.
- Removed owner-control navigation from the customer-facing website.
- Preserved the original public website design and added the owner-promotion section without replacing the site with the backend's embedded preview HTML.
- Updated the Android asset copy and rebuilt both native release packages from the revised project.

## Verification performed

- Python compile checks passed.
- Existing QA suite: **22/22 checks passed**.
- JavaScript syntax checks passed for the customer page, owner-control page and owner app shell.
- Owner promotions regression test passed: create, persistent record, stored fee exemption, public publication, pause and republish.
- Local APK and EXE download routes returned HTTP 200 with the expected APK ZIP and Windows PE signatures.
- Android APK signature verification passed.
- Windows EXE build completed successfully.

## Release artifacts

- `downloads/Skillvaya.apk` — signed release APK.
- `downloads/Skillvaya.exe` — rebuilt portable Windows EXE.

## Not yet complete — do not call public launch ready

- The website is still running locally; it has not been deployed to a public HTTPS domain.
- The source has not yet been pushed to the new private GitHub repository.
- The Android and Windows builds still use local/offline mode because no public production URL has been configured. Different installations therefore do not yet share one online database.
- The public owner route and hosted owner authentication still need a production security review before exposing the owner workspace to the internet.
- PayFast live merchant approval/credentials, public ITN callback testing, SMTP delivery, external-network download tests, physical Android device testing and clean-PC EXE testing remain release gates.

## Rollback

Pre-upgrade backups were created in the Skillvaya project folder. The release signing keystore and its password file remain under the local Skillvaya AppData directory and are not included in the source repository.
