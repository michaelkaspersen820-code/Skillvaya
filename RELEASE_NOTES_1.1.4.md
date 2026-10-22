# Skillvaya 1.1.4 — Branded loading screen

## Change
- Replaced the plain native startup text with the Skillvaya-branded loading screen: dark navy background, Skillvaya wordmark, “Loading” label, and animated one/two/three-dot indicator.
- Kept the splash screen above the hosted WebView until the real Skillvaya page is detected, so the Render wake-up/status page is not presented as the app's own interface.
- Added a retry for the hosted page while the service is waking up.
- Kept the same package/application ID, permissions, hosted app URL, WebView settings, and camera/file-picker flows.
- Updated Android release version to 1.1.4 (versionCode 15).

## Verification
- Android release APK build: successful.
- APK package metadata: `za.co.skillvaya.app`, version 1.1.4, versionCode 15.
- APK signature verification: successful (APK Signature Scheme v2).
- Existing backend Python source and mirrored Android Python source remain byte-for-byte identical.
- A physical Android launch test could not be performed because no Android device/emulator was connected during this build.
