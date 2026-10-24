# Skillvaya Owner App Upgrade Plan
Date: 2026-10-24
Status: DESIGN APPROVED FOR IMPLEMENTATION — NOT YET IMPLEMENTED/VERIFIED

## Scope boundary (critical)
- Entry point: Accounts screen > Account tab > "My Worker Side" button.
- Replace only the old controller/owner-side experience opened from that button with the new Skillvaya Owner App.
- Preserve everything else exactly as it currently works: customer/provider screens, account flows, worker side, listings, search, messaging, quotes/jobs, subscriptions, payment/PayPal configuration, sign-in, and existing APIs/data.
- Do not remove or rename the "My Worker Side" button. It becomes the entry to the redesigned owner/admin console.
- Keep changes additive and isolated; do not rewrite unrelated modules or database schema without evidence it is required.

## Design
Dark navy + blue/cyan Skillvaya branding, accessible responsive layout, clear side navigation and compact dashboard cards.
Panels:
1. Owner Login / protected admin entry (respect existing authentication; never expose admin controls to ordinary users).
2. Owner Dashboard: user/provider/listing/revenue/subscription stats, activity feed, shortcuts.
3. Customers & Providers: searchable/filterable tables, details, active/suspended/banned states.
4. Email Centre & Inbox: inbox, sent, templates, search, compose; use existing mail integration.
5. Reports, Warnings & Complaints: triage, assign/status, resolution history.
6. Payments & Subscriptions: transactions, plans, subscription status, payouts; use existing live PayPal/payment integration, do not switch sandbox/live settings.
7. Advertising & Promotions: promotion/banner/featured listing management.
8. Platform Settings: existing supported settings, security, appearance, integrations, notifications, maintenance controls.
Footer/quick actions: Ban Users & Providers, Complete User Control, Real-Time Insights, Flexible Settings.

## Moderation and safety controls
- Add per-user/provider "View", "Suspend", and "Ban" actions, with confirmation dialogs, reason, actor/time audit trail, and ability to review/appeal/unban if supported by existing data model.
- Server-side authorization is mandatory for every privileged operation; hiding a button is not security.
- Bans must stop access to protected actions and be enforced by backend authorization/session checks, not merely change the UI.
- Never delete accounts/data as a side effect of banning. Preserve records and transactions.
- Protect against accidental owner lockout; confirm destructive/high-impact actions and log them.

## Implementation and verification
1. Inspect current production-based worktree and map the exact route/function behind "My Worker Side".
2. Save a clean baseline commit/backup before editing; record git status and current production commit.
3. Implement the owner console in isolated templates/routes/components and reuse existing APIs/auth.
4. Wire each visible control to a real supported operation; if a capability lacks a backend, implement the full backend and tests or clearly mark it unavailable—no decorative/inert buttons.
5. Add role/permission checks and audit logs for moderation/admin endpoints.
6. Run Python compile, lint/available tests, route smoke tests, authorization tests, and regression checks for existing customer/provider/payment flows.
7. Build Android release APK and install/launch smoke test only after source checks pass.
8. Deploy through the existing Render/GitHub workflow only after checks pass; verify the live owner console and key preserved flows.
9. Report commit, build result, deployment result, exact tests and any remaining gaps. Never claim complete based on build success alone.

## Acceptance criteria
- "My Worker Side" opens the new owner console at the intended account entry point.
- Old controller UI is no longer shown in that path.
- All other app areas remain unchanged and pass regression checks.
- Admin dashboard and all panels render on phone and desktop.
- Search/filter/details work; suspend/ban actions persist server-side, are permission-protected, have reason/audit trail, and enforce access restrictions.
- Existing live PayPal/payment setup remains untouched.
- APK build/install and Render deployment are verified independently.

## Current execution checkpoint � 2026-10-24
- Created isolated branch `feature/owner-app-full-console-20261024` from latest `origin/free-hosting-postgres`.
- Saved visual design source as `owner_app_redesign.html` and replacement script as `apply_owner_app_redesign.py`.
- Replaced only `OWNER_APP_HTML` in `app.py`; created timestamped pre-change backups. `OWNER_HTML` and its existing backend controls were not rewritten.
- New shell includes protected owner login, responsive navy/cyan dashboard, sidebar navigation, user/provider management entry, dedicated ban/suspend shortcut, complaints, payments, inbox, promotions, settings, and a dashboard/area switcher.
- Existing owner-control HTML is fetched with the authenticated Bearer token and mounted into same-origin `srcdoc`, so its API calls retain existing token-based protections. This integration still needs browser-level verification.
- `python -m py_compile app.py`: PASS.
- `test_owner_control_route_auth.py`: PASS after updating its assertion for the new Owner App shell. Unauthenticated owner APIs remain 401; anonymous `/owner-control` still redirects to `/owner-app`.
- `git diff --check`: PASS.
- Android release APK build: SUCCESS. APK SHA256: `21F9072F30CF816D1A2B8BB7720CB97F55794FAD54CB76544D3DEF5FE0151065`.
- APK installed on connected Samsung A14; `za.co.skillvaya.app/.MainActivity` launch verified.
- NOT YET COMPLETE: browser-level verification of every owner area, actual ban/suspend action flow and audit trail; full DB-backed regression suite (requires isolated PostgreSQL `DATABASE_URL`); production deployment/Render verification. Do not call this release finished or deploy until those checks pass.
