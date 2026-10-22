# Skillvaya 1.1.3 - Customer navigation and provider directory dropdown

## Fixes
- Saved Providers and My Jobs & Quotes now open a dedicated, full-screen account workspace rather than switching the main page to Profile and forcing a scroll-to-top jump.
- The account workspace remains a separate UI even when its list is empty, with clear empty-state messages and a Back to Profile control.
- Background scrolling is locked while the workspace is open; closing it restores the exact previous document scroll position. Escape also closes the workspace.
- The main customer directory now groups the provider cards inside a polished, keyboard-accessible dropdown. Its count and helper text update with search/filter results, and the empty-provider state remains visible inside the expanded dropdown.
- Existing provider cards, profile detail navigation, saved-provider controls, and provider contact actions remain intact.
- Root and Android embedded Python application sources are synchronized.

## Verification
- 17/17 local Playwright checks passed for dropdown expand/collapse, provider detail click-through, separate Saved Providers and My Jobs workspaces, empty states, background-scroll lock, exact scroll restoration, Escape-to-close, empty provider directory and recovery after restoring results. An additional 4/4 responsive viewport sweep passed at 320, 390, 768 and 1365px without horizontal overflow or JavaScript errors.
- Python compilation passed for both root and Android embedded app sources.
- This is a UI-only change; no PayPal mode, credentials, live transactions, or billing configuration were changed.

## Remaining device/deployment checks
- Native camera launch/capture still requires a connected physical Android device or bootable emulator.
- Production behavior changes only after the latest commit is deployed to Render; verify the hosted release after deployment.
