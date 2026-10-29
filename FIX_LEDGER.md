# SkillVaya Recovery / Fix Ledger

Purpose: preserve the intent of production fixes across restores. Do not revert a fix without recording why and checking dependent screens.

## Target 56 — 2026-10-29

- `SV56-HDR-01` — `app.py` and `android-native/app/src/main/python/app.py`: release-36 CSS overrode the earlier fixed global masthead (`header.top`) with `position: sticky`. The fixed masthead rule must remain authoritative so the main SkillVaya header does not move with scrolling.
- `SV56-RATING-01` — both app entry points: platform/provider rating renderers emitted literal question marks or corrupted replacement glyphs instead of star symbols. Render the Unicode black star (`★`) independent of icon fonts.
- `SV56-WF-NAV-01` — both WorkFinder files: bottom navigation was hidden whenever its token was absent. Keep the five destinations visible on WorkFinder dashboard pages; protected actions still require authentication.
- `SV56-WF-HDR-01` — both WorkFinder files: pin the WorkFinder header to the viewport and reserve content space so it does not cover the first card.

Scope restriction: only reported regressions are targeted. No pricing, payments, database schema, owner controls, or unrelated redesigns intended.
