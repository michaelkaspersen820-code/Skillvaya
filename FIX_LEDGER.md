# SkillVaya Recovery / Fix Ledger

Purpose: preserve the intent of production fixes across restores. Do not revert a fix without recording why and checking dependent screens.

## Target 56 — 2026-10-29

- `SV56-HDR-01` — `app.py` and `android-native/app/src/main/python/app.py`: release-36 CSS overrode the earlier fixed global masthead (`header.top`) with `position: sticky`. The fixed masthead rule must remain authoritative so the main SkillVaya header does not move with scrolling.
- `SV56-RATING-01` — both app entry points: platform/provider rating renderers emitted literal question marks or corrupted replacement glyphs instead of star symbols. Render the Unicode black star (`★`) independent of icon fonts.
- `SV56-WF-NAV-01` — both WorkFinder files: bottom navigation was hidden whenever its token was absent. Keep the five destinations visible on WorkFinder dashboard pages; protected actions still require authentication.
- `SV56-WF-HDR-01` — both WorkFinder files: pin the WorkFinder header to the viewport and reserve content space so it does not cover the first card.

Scope restriction: only reported regressions are targeted. No pricing, payments, database schema, owner controls, or unrelated redesigns intended.

- `SV56-SERVICE-01` — both app entry points: the public bottom-tab handler redirected guests and customers into `openProviderWorkstation()` when they selected Services. Remove that misroute so the Services tab can render the public provider directory; provider work tools remain available through their dedicated entry point.
- `SV56-RATING-02` — both app entry points: replace the literal question-mark character in the platform-rating button template with the Unicode star (`★`).

- `SV56-SERVICE-03` — live browser verification showed the Services tab displayed the provider-only workstation to a signed-out visitor after the first redirect fix. Final route guard now sends guests/customers to the public directory and preserves the workstation for provider/admin roles.

- `SV56-WF-NAV-02` — both WorkFinder files: the bottom tabs were explicitly hidden on page 15 (conversation composer). Keep all five tabs visible in conversations too, and reduce the chat viewport height to reserve space above the fixed tab bar so the composer remains visible.

- `SV56-WF-PROFILE-01` ? both WorkFinder files: remove the hard-coded `YK` fallback from the profile-photo circle. Keep the photo preview/click target and upload flow unchanged; an empty profile photo now shows a clean empty circle rather than fabricated initials.
- `SV56-ACCOUNT-SCROLL-01` ? both app entry points: constrain Account mode to the device viewport and make `main.wrap` the scroll container, reserving space for the fixed bottom navigation so account content cannot scroll underneath the tabs.
- `SV56-WF-VOICE-01` ? both WorkFinder files: display interim speech recognition results in the composer while listening, while preserving the existing final-result de-duplication and send path.
- `SV56-NATIVE-VOICE-01` ? Android `MainActivity.java`: retry recoverable Android speech-service interruptions within the same user-started dictation session, preserving the existing text callbacks and explicit stop action.

Validation note: source syntax, diff whitespace, release version metadata, signing, and device install must be checked before calling the v56 refresh complete. Microphone capture still requires an on-device spoken-phrase test; static/build checks alone do not prove transcription quality.

- `SV57-AUTH-RESTORE-01` ? main app (web and Android embedded copies): wait for the existing `/api/me` session check before dismissing the startup splash/deciding whether to show first-launch sign-in. Existing persisted credentials are used; this does not create or sign out accounts.
- `SV57-WF-SESSION-01` ? WorkFinder (web and Android embedded copies): read the same token from localStorage or sessionStorage, cache restored identity in both, and preserve credentials on transient/network/data-loading errors. Only an explicit WorkFinder sign-out or an authorization response (401/403) clears saved credentials.
- `SV57-ACCOUNT-HEADER-01` ? main app (web and Android embedded copies): keep the Account identity heading pinned at the top of the Account scroll viewport; this style is scoped to Account mode.

- `SV58-RATING-01` ? main app rating selection updates immediately and uses the aggregate returned by the save response instead of waiting for an extra ratings request.
- `SV58-ACCOUNT-HEADER-02` ? Account header sticky offset is set below the fixed 78px main header so it remains visible during Account scrolling.
- `SV58-SESSION-PERSIST-02` ? successful login persists the session across app closes/updates regardless of the optional remember-me checkbox; explicit sign-out remains the way to clear it.
- `SV58-CONVERSATION-01` ? main conversation shell renders immediately; empty provider-side conversations can send the first message rather than only showing a waiting notice.
- `SV58-WF-COMPOSER-01` ? WorkFinder composer uses fixed compact grid columns to prevent the Speak/microphone/send controls from overlapping or being pushed off-screen.

- `SV58-ACCOUNT-HEADER-03` ? corrected the Account header using viewport-fixed positioning (rather than sticky positioning inside the nested scroll container) and reserved layout space below it.
- `SV58-WF-COMPOSER-02` ? constrained all five WorkFinder composer columns to fit within narrow mobile widths without horizontal overflow.

- `SV58-AUTH-FAST-01` ? successful signup/login reuses the user object returned by the authentication endpoint instead of immediately making a redundant `/api/me` request; background profile and message refreshes remain intact.

- `SV58-SESSION-MIGRATE-01` ? when an existing saved session validates, migrate its token from session storage to durable local storage so users who had unchecked Remember Me can stay signed in across future app closes/updates.

- `SV58-CHAT-VIEWPORT-01` ? main SkillVaya conversation is constrained to the area between the app header and fixed bottom navigation; message bubbles scroll within that area and the composer stays at the bottom.
- `SV58-CHAT-EMPTY-02` ? opening an existing contact with no messages no longer redirects a customer/admin back to the provider/home screen; the empty conversation remains open so the user can compose the first message.
- `SV58-CHAT-MIC-03` ? the empty-conversation voice control shows the microphone icon and accessible voice-typing label rather than the word ?Speak?.

- `SV58-CHAT-FOOTER-02` - empty conversations now include the same flexible message area as populated conversations, keeping the composer at the bottom; the broken microphone label is replaced with a microphone glyph; scoped CSS constrains the voice control to a consistent 44-48 px button.

- `SV58-CHAT-CACHE-04` - preserve whether the message-list request actually succeeded in the conversation cache; a valid cached empty thread is reused instead of issuing the slow full-inbox request again, while failed message fetches are retried.
- `SV58-CHAT-MIC-04` - use a stable HTML microphone entity in empty and populated conversations and remove the duplicate title attribute.

- `SV58-CHAT-ENTRY-05` - the initial Contact-provider path now includes a flexible message region above the composer, so the first-message text box also stays at the bottom of the conversation viewport.
- `SV59-VOICE-01` - Android-native dictation now allows longer natural pauses (10-second complete silence / 5-second possible-complete silence) and retries recoverable Android client errors while the user-initiated voice session remains active. Scoped to `MainActivity.java`; no conversation markup, CSS, message API, account/session logic, or WorkFinder navigation changed. Release: 7.1.5.6 / versionCode 59.

## Target 74 - 2026-10-30 (7.1.7.1 / versionCode 74) - full click-through audit, functional fixes only

- `SV74-CONTACT-01` - both app entry points: the Contact Skillvaya form (`#platformContactForm`) called `submitPlatformContact(event)`, which was never defined, so the "Continue to email" button did nothing. Added the missing handler next to `msg()`: validates, then opens the device email app with the enquiry prefilled to skillvaya@gmail.com (the native shell already routes mailto: links to the email app). No markup, CSS or layout change.
- `SV74-PROVIDER-OPTIN-01` - both app entry points: `becomeServiceProvider()` reported progress through `#providerOptInMsg`, which no longer exists in any markup, so Account > Become a Provider threw `Cannot set properties of null (setting 'className')` AFTER the server had already upgraded the account, leaving the Provider Studio/plans unopened. Messages now go through `providerOptInNotice()`, which uses `#providerOptInMsg` if present and otherwise the existing `#providerProfileNotice`.
- `SV74-MSG-01` - both app entry points: `msg(id,...)` now returns quietly if the target element is missing, so a stale element id can no longer abort a whole user flow.
- `SV74-NATIVE-BACK-01` - Android `MainActivity.java`: apps targeting SDK 36 no longer receive `onBackPressed()` on Android 16, so the back gesture would have left the app instead of going back through the WebView history. Registered an `OnBackInvokedCallback` (API 33+) with the same behaviour as the legacy handler; `onBackPressed()` is kept for older Android.
- `SV74-TEST-01` - added `tests/test_button_wiring_contract.py` (5 checks: every inline handler resolves to a defined function in both runtime copies; contact form; null-safe `msg()`; become-provider notice; Android back callback). `test_job_hub.py`: provider accounts are allowed on the shared favorites endpoint by current server policy, so the stale 401 expectation now expects 200.

Scope restriction: no layout, navigation, pricing, payments, database schema, owner controls or unrelated redesign changed.
Validation: both app.py copies compile; 25 contract tests pass; 12 root-level backend suites pass (Job Hub 17/17); 61 GET API paths return no server errors for customer and provider tokens; a real-browser (Chromium, phone-sized) click-through of 9 app screens (Customer, Services, Provider Studio, Account, Settings, Messages, Terms, Contact, Workstation) as guest, customer and provider found only the defects above (one transient local connection refusal under heavy concurrent load did not reproduce in isolation). NOT proven by this audit: two-device call answer/audio, long dictation, Play purchases and push delivery on physical phones, and any screen that needs paid-tier or real-payment state.
