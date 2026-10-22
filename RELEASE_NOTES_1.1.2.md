# Skillvaya 1.1.2 - Full UI and listing integrity release

## Fixes and improvements
- Replaced profile photo picker overlays with accessible, keyboard-focusable Choose profile picture and Take photo buttons. The camera input keeps `capture="environment"`; image selection, preview, size/type validation, upload, and input reset are covered by browser automation.
- Fixed duplicate provider-detail screen IDs that could make the browser open the wrong hidden detail container.
- Added safe bottom padding to the customer layout and category scroller so the fixed navigation does not cover the last category controls.
- Added service area, public phone, WhatsApp, and contact-email fields to owner-created business listings, with required service area and phone for business profiles.
- Added edit support for owner-created businesses, adverts, and apps.
- Linked owner business promotions to their public directory entries. Pause suspends the public listing, republish restores it, and removal hides both records. Added a migration/backfill for older owner listings.
- Protected the hosted owner-control page with the owner session gate and clarified the security notice.
- Removed the stale instruction to use PayPal Sandbox from the retired PayFast endpoint response. The owner payments panel now labels OAuth as Live or Sandbox according to the configured mode. The existing PayPal mode and credentials were not changed.

## Verification
- Customer browser UI: 78 automated checks across desktop and 390px mobile, including routes, unique DOM IDs, no horizontal overflow, provider/terms/profile navigation, terms gates, account creation and sign-in, profile editing, photo chooser button actions, image validation and upload, logout, and no uncaught JavaScript exceptions or HTTP 5xx responses on the isolated test server.
- Owner UI: 60 desktop/mobile checks across every owner-control workspace, including unique DOM IDs, owner business create/edit/pause/republish/remove actions, and a local Live-mode/no-credentials check confirming the panel says "Live OAuth" rather than "Sandbox OAuth".
- Category navigation: all 143 category buttons clicked and verified on both desktop and mobile (286 category actions total); category screen/back navigation passed with no JS errors, HTTP 5xx responses, or horizontal overflow.
- Public provider-detail flow: 9 checks passed for search, detail navigation, safe WhatsApp/email/website links, back navigation, and sign-in gates for save/message/report actions.
- Responsive sweep: 27 route/viewport checks passed across 320, 360, 390, 430, 768, 1024, 1280, 1365 and 1920px widths for the customer site, owner app and owner control; no horizontal overflow or uncaught JS errors.
- Owner-route security regression: an unauthenticated request to `/owner-control` redirects to `/owner-app`, and owner promotion/payment APIs return HTTP 401 without an owner session.
- Owner promotion regression tests now verify contact fields and synchronization with the public directory.
- Backend regression suites passed: 37 one-go checks, 17 job-hub checks, owner-promotion regression, owner terms, profile-photo end-to-end, owner-bootstrap, and 10 mocked PayPal checkout checks. Legacy owner-promotion migration/backfill regression also passed.
- No live order, capture, refund, mode switch, or credential change was performed. The configured live PayPal OAuth path and a real buyer-approved transaction are not certified by this release; the mode-sensitive label was verified with a local live-mode/no-credentials test.

## Limits
- Real Android camera-app capture still requires a bootable Android test device/emulator. Browser camera-input and picker-button actions are verified; they are not a substitute for a native Android camera test. The installed Android emulator stayed offline during this audit, and no physical device was connected.
- A real buyer-approved PayPal payment/capture, native Android camera launch/capture on a bootable device, email delivery, and independent security/legal review remain separate release gates.
