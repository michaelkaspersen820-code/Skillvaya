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

### Target 74 (round 2, same unreleased 7.1.7.1 / versionCode 74) - message/call speed and reliability

Measured on production before changing anything: requests that touch the database took 2.2-3.6 s (about 0.43 s for requests that do not), because every query opened a new PostgreSQL connection.

- `SV74-PERF-01` - both app.py copies: hosted PostgreSQL connections are now pooled (6 warm connections, idle validation after 20 s, one safe replay of the first statement if the server dropped a pooled connection, auto-prepare disabled for pooler safety). Kill switch: env `SKILLVAYA_DB_POOL=off`. Verified on a real local PostgreSQL: a call-check poll went from about 2.3 new connections / ~2 s (modelled) to 0-1 connection for 30 polls.
- `SV74-PERF-02` - the 1-second call poll no longer writes to the database every time (missed-call sweep runs at most every 15 s per process), the Google Play subscription refresh runs at most once a minute per provider, and `setting()` is cached for 5 s (cleared when the owner changes a setting).
- `SV74-PERF-03` - 20 `CREATE INDEX IF NOT EXISTS idx_sv_*` indexes (messages, calls, sessions, contacts, businesses, payments, push tokens, etc.) built in a background thread at startup so the HTTP port still binds immediately.
- `SV74-RT-01` - `svStartMessageLiveUpdates()` existed but was never called (also true on the live site), so message polling never ran. It is now started from `sessionInfo()` after sign-in/session restore.
- `SV74-RT-02` - new `GET /api/messages/pulse` (latest message id + unread count, same visibility rules as `/api/messages`). The client checks it every 1.5 s inside an open chat and every 3 s on the Messages list and only then downloads the list; the 10 s full poll remains as a safety net. Real-browser result: a reply shows on screen in about 2.4 s (before the 1.5 s change; never before that).
- `SV74-RT-03` - chat sends no longer wait on Firebase: `fcm_send_async()` sends in a background thread (send request measured at 8-11 ms while Firebase was artificially delayed 2.5 s), and Firebase is initialised at startup (`fcm_prewarm`). Server copy only (the embedded Android copy intentionally has no Firebase code).
- `SV74-CALL-01` - calls previously used STUN only (no TURN relay), which fails across many mobile-carrier NATs. New authenticated `GET /api/ice-servers` returns STUN plus a TURN relay when the host sets `SKILLVAYA_TURN_URLS` with either `SKILLVAYA_TURN_USERNAME`+`SKILLVAYA_TURN_CREDENTIAL` or `SKILLVAYA_TURN_SECRET` (coturn time-limited credentials). The client fetches it (2.5 s timeout, falls back to STUN) and prefetches it at sign-in. NO TURN SERVER IS CONFIGURED YET: set those variables on the host to benefit.
- `SV74-TEXT-01` - visible text that had lost characters to literal `?`: Work Finder bottom-tab icon (now a diamond glyph like its siblings), rating messages, profile identity line, plan headings, receipt line, and WorkFinder 'Upload portfolio'.
- `SV74-GP-01` - the host variable is saved as `GOOGLE_PLAY-SERVICE_ACCOUNT_JSON` (hyphen) but the code read `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`, so Play credentials were never loaded. Code now accepts both; rename the host variable to the underscore form when convenient.
- `SV74-TEST-02` - `tests/test_realtime_performance_contract.py` (10 checks). Totals: 35 contract tests, 12 root backend suites, 41/41 PostgreSQL end-to-end checks, plus the real-PostgreSQL pool/FCM/pulse/ICE/index verification script.

Not proven by this round: real push delivery to a phone, two-device call audio/connection (needs a TURN server for carrier networks), and the production latency after deploy (measure again once live). Remaining latency floor is the network round-trip to the Render region (about 0.4 s from South Africa); a Render region and Neon region that are close to each other and to users would reduce it further.

### Target 74 (round 3, same unreleased 7.1.7.1 / versionCode 74) - answering calls on the phone, blocking, audit

Reproduced the call flow with two real browser sessions (customer calls provider, provider answers) with the recipient on Home, Account, Messages and Services: incoming panel shown in 0.5-0.6 s, Accept is the top element and tappable, call connected in about 1 s, no JS errors. So the web logic is sound; the phone-specific defects were in the Android layer.

- `SV74-ANDROID-CALL-01` - `MainActivity.java`: the WebView never allowed media playback without a direct tap (`setMediaPlaybackRequiresUserGesture(false)` was missing), so remote call audio and the in-app ring tone, which start from timers/network events, could be blocked. Now allowed.
- `SV74-ANDROID-CALL-02` - `MainActivity.java`: microphone and camera permission are now requested at launch together with notifications (new `CALL_STARTUP_PERMISSION_REQUEST`), so answering a call never stalls behind a first-time permission dialog.
- `SV74-WF-BLOCK-01` - WorkFinder (`static/workfinder.html` and the Android copy): `blockUser()` existed but nothing called it. Added a Block button in the conversation header, blocked people's conversations are hidden, blocks persist in localStorage, and unblocking persists too.
- `SV74-AUDIT-03` - static check of /, /workfinder, /customer-app, /owner-app, /terms, /privacy: no inline handler references a missing function. Click-through: home page 37 controls and WorkFinder-as-customer 20 controls with no JS/console errors or HTTP 5xx. The bounded customer-app re-crawl hung on one control and was stopped (round-1 click-through of all 9 customer-app views x 3 roles had passed). Unreferenced legacy functions remain in the customer app (`rateCustomer`, `replyMessage`, `verifyPayment`, ...) and were left alone.
- `SV74-TEST-03` - 2 more regression checks (37 contract tests total).

Still not proven: answering on a real phone (no device connected via adb), a TURN relay for carrier networks (host variables `SKILLVAYA_TURN_*` not set), and push delivery to a device.

## Target 75 - 2026-10-30 (7.1.7.2 / versionCode 75) - one header standard on every screen

Owner request: every screen header must look the same, text must stay inside it, the Services heading was far too big, and headers must stay on screen (including WorkFinder). Version 74 is already on Google Play, so this is the next version.

Real-browser audit at 390x844 (and 360x740) of every customer-app, provider, account, messages, terms and WorkFinder screen found: headers from 62 px to 284 px tall (Services workstation hero 284 px, Contact 190, Account 143, Provider tools 132), titles from 19 px to 38 px, a hard-coded 76 px sticky offset that left a gap of scrolling content above the header on screens without the masthead and overlapped the masthead (94 px) on Home, a sticky Account/Contact hero covering a third of the phone, and WorkFinder page titles that scrolled away.

- `SV75-HDR-01` - one header standard (`SV75-HEADERS-01` block at the end of the customer-app CSS, both `app.py` copies): every screen header is a full-width navy bar, 62 px (min) to 84 px (max), 20 px bold title (18 px on 360 px phones), one-line 12 px subtitle, text clipped with an ellipsis so it can never leave the bar, eyebrow/plan chips hidden, arrow-only back buttons. Covers Services workstation, Contact, Provider studio, Provider tools, Account, Messages, category list, account sub-pages (My Jobs & Quotes etc.), Team assignments, Terms, and the provider-detail back bar. Specificity is raised with `:not(#z):not(#z)` so the older id-based `!important` rules cannot win.
- `SV75-HDR-02` - sticky offset is now real: `svSyncHeaderOffset()` sets `--sv-screen-header-top` to the bottom edge of the masthead when it is visible and 0 when it is hidden (MutationObserver on body class and masthead, resize, orientation). Removes the gap above headers on Contact/Terms/Provider studio and the overlap on Home. Account stays pinned (fixed) and the page below now starts 76 px down instead of 178 px. Account sub-pages: bar now at the very top and the cards start under it (they were pinned at 145-180 px for the old tall block).
- `SV75-HDR-03` - Home masthead is 63 px on phones (was 94): tagline hidden, `.nav` min-height 62 px.
- `SV75-WF-HDR-01` - WorkFinder pages get the same bar: first heading (+ subtitle) of every page is wrapped by a small observer into a sticky `.wf-pagehead` under the app bar; row headers (Messages + New button) and the chat header use the same bar; "Back" first-buttons become a back bar. Added `overflow-x:clip` fallback because `overflow-x:hidden` on both `html` and `body` silently disabled `position:sticky` (page titles scrolled away on every scrolling page).
- `SV75-WF-CHAT-01` - pre-existing bug found by the audit: the WorkFinder chat header sat at y=12 behind the 60 px app bar, so Back, the partner name and the Block button added in round 3 were hidden. The chat page now starts under the app bar.
- `SV75-HDR-04` - Terms page, Privacy/Policies page, Account-deletion page and Owner dashboard title bar are compact and sticky (`.top` 20-22 px title).
- `SV75-TEST-04` - `tests/test_header_standard_contract.py` (13 checks; 50 contract tests in total).

Measured after the change (Playwright, phone widths): every header 62 px (back bar 56 px) with a 20 px / 800 title; no horizontal scroll on any screen; bars lock at top 0 (or just under the masthead) after scrolling.

Not covered: owner dashboard is a desktop layout (sticky title bar added, not re-designed for phones); the WorkFinder "apply" page needs a job in the database to render, so it was not measured.

### Target 75 (round 2, same unreleased 7.1.7.2 / versionCode 75) - speed on every screen, messages and calls

Owner request: every screen, Messages and calls must appear fast. Measured first with a real browser (phone CPU 4x slower, 300 ms network latency) against the real app on real PostgreSQL behind a proxy that delays each query 150 ms (the hosted database costs about 0.2 s per query on top of about 0.4 s network from South Africa).

Root causes: every database call cost 3 network round trips (psycopg's implicit BEGIN, the query, COMMIT) and every signed-in request paid it twice (session check, then data), so /api/me cost 6 trips and opening Messages 9; start-up waited for /api/me, then loaded the directory, then waited up to 1.8 s for categories before the splash left; Messages, a conversation, a category and the Services tab always waited for the network even when the data was already on the phone; the app shell and logo were re-downloaded on every launch.

Median of 3 rounds, old code (what was live) -> new code:

| What the user does | Before | After |
|---|---|---|
| Re-open the app (second launch) | 3421 ms | 873 ms |
| First ever open | 3989 ms | 2268 ms |
| Open a conversation | 2410 ms | 12 ms |
| Open a category | 2037 ms | 217 ms |
| Message delivered after tap Send | 1266 ms | 490 ms |
| Provider opens Services (first time) | 1233 ms | 620 ms |
| Open Contacts after the app was closed and reopened | 2164 ms | 23 ms |
| Call: the other phone rings after you tap Call | 2421 ms | 1729 ms |
| Call: connected after the other person taps Accept | 6066 ms | 4457 ms |
Server (150 ms per query): /api/me 941 -> 170 ms, message list 1406 -> 481 ms, send message 1254 -> 482 ms, call poll 937 -> 327 ms, call signal sync 3 trips -> 1.

- `SV76-PERF-01` - PostgreSQL connections are autocommit; a transaction (BEGIN) is opened only when the first write happens, commit/rollback cost nothing when none is open. Reads are exactly one round trip.
- `SV76-PERF-02` - `execute_atomic` (one statement = one trip) and `execute_batch` (psycopg pipeline: several reads in one trip) with SQLite fallbacks (`db_atomic`, `db_batch`); used by message send (message + enquiry in one statement), mark-read, call start (call row + chat invitation in one statement), call accept/candidate/end, call sync (call + signals in one trip) and /api/me (single query).
- `SV76-PERF-03` - app shell: ETag/304 for /customer-app and /workfinder, logo and icon cached for a day, service worker v4 serves the saved app after 2.5 s so a sleeping server never leaves a blank screen (works with the server completely down).
- `SV76-SPEED-01` - start-up runs session, directory, rating and categories in parallel and no longer waits for the session or categories; the provider directory, favourites, inbox and provider tools paint from the last visit (localStorage) and refresh in the background; categories open from the list already on the phone; a conversation opens from memory when the inbox is under 2 minutes old and is re-checked with the server in the background; anything that adds a message (send, attachment, call invitation) discards the in-memory copy. Private caches (inbox, provider plan) are wiped on logout; the directory cache never stores a user's personal ratings.
- `SV76-WF-SPEED-01` - WorkFinder loads profile, applications, saved jobs, conversations and /api/me in one trip instead of three.
- `SV75-TEST-05` - `tests/test_speed_contract.py` (18 checks) plus the older message-freshness contract updated to the new, still strict, rule. 68 contract tests, 12 backend suites and PostgreSQL QA 41/41 pass.

Not fixed (needs the owner): the free Render server sleeps after 15 idle minutes and the first request after that can take about 50 s (a paid Render plan or a keep-awake ping fixes it; a ping was not added because the workspace has 3 services sharing 750 free hours); Render's region is far from South Africa (about 400 ms per request before any work happens, a Frankfurt region would roughly halve it); calls on mobile networks still need a TURN relay.
