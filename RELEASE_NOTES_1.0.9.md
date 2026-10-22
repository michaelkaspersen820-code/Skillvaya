# Skillvaya coordinated release 1.0.9

## Included

- Customer Job Hub: request work from an active provider, include area/date/optional budget, review provider quotes, accept a quote, and track scheduled/in-progress/completed work. Customers can cancel eligible open jobs.
- Provider quotation workflow: providers can quote only jobs assigned to their business, with rand amount, ETA and scope. The customer owns quote acceptance; accepting one quote declines competing quotes for the same job.
- Saved providers: customers can save/unsave provider listings, and retrieve their saved list from Profile. Favorites are stored per customer account in the application database.
- Android photo controls remain in the release: direct-touch picker, camera handoff, and upload/save workflow.
- Existing directory search and category matching, profile/account functions, messages, ratings, complaints, owner promotions, owner controls, PayPal checkout/refunds, and free owner listings retained.

## Regression evidence

- `qa_one_go.py`: 37 checks passed.
- `test_job_hub.py`: 17 checks passed, including favorites authentication/persistence/toggle, job isolation, quote ownership, acceptance, lifecycle and completion/cancellation constraints.
- `test_owner_promotions.py`: passed after updating a stale UI assertion to match the agreed simplified Owner App navigation.
- `test_profile_photo_e2e.py`: passed for account signup, upload, API response, profile reload and database persistence in the test environment.
- `verify_paypal_checkout.py`: 10 mocked checkout/capture/refund tests passed. These are simulated provider responses; they do not prove a live payment was sent or received.
- `verify_payfast_checkout.py`: confirms the retired PayFast route is disabled; PayPal remains the advertised provider.
- `test_deployment_owner_bootstrap.py`: passed.
- Python compilation and inline JavaScript syntax checks passed.
- Android release build: signed release APK created as version 1.0.9 / versionCode 10.

## Remaining release gates that cannot be honestly marked complete by source/build tests alone

- Test the APK on a physical Android phone over ADB, including real file picker, camera capture, profile upload, back navigation and account flows. No physical device was connected during this build.
- Complete a real PayPal sandbox checkout and refund using the configured live hosted callback path; automated checkout tests use mocks.
- Configure and verify SMTP delivery before claiming email delivery works.
- Confirm backup/restore, session expiry/revocation, rate limiting, and security review against the actual hosted database and deployment.
- Obtain legal review of South African terms/privacy/consumer/payment wording before public commercial launch.

This release is built and regression-tested; the remaining items above are explicitly not represented as physically or externally verified.
