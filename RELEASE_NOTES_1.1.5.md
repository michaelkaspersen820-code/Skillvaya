# Skillvaya 1.1.5 — Messages & comments workspace

## Changes
- Replaced the misleading “My messages” label with “Messages & comments”.
- Opened messaging in its own full-screen account workspace instead of switching the profile tab and jumping to the top.
- Grouped saved messages by provider/customer pair into persistent conversation threads, displayed in chronological order.
- Added message bubbles identifying who sent each message, conversation refresh, and a reply/follow-up comment box for both sides.
- Updated provider reply authorization so a provider may reply to an existing saved message thread (including a job-request conversation), without needing a separate enquiry record. The provider must own the listing and the customer must already have a conversation with that listing.
- Preserved existing jobs, saved providers, customer/provider roles, and payment settings.

## Verification
- Python compile and JavaScript syntax checks passed.
- Messaging API end-to-end: customer starts a conversation, provider sees it and replies, customer sees both messages in the same thread.
- Browser UI checks passed: dedicated workspace opens, saved conversation and reply input render, opening/closing does not jump to the top, and no browser JavaScript runtime errors.
- Existing QA: 37 general checks, 17 Job Hub checks, owner-control route authorization and owner-promotion migration passed.
- Android APK rebuilt with versionName 1.1.5, versionCode 16.
