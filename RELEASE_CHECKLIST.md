# Skillvaya — Release Checklist

Use this checklist for the first public release. A checked local build is not the same as a deployed, production-ready service.

## Built locally
- [x] Signed Android APK created at `downloads/Skillvaya.apk`.
- [x] Portable Windows EXE created at `downloads/Skillvaya.exe`.
- [x] Local installer endpoints tested for HTTP 200 and correct file type.
- [x] Separate Owner App and Customer App routes exist.
- [x] Owner App website/share controls added to source.
- [x] Website share buttons added to source.
- [x] PayFast integration and sandbox verification scripts exist.

## Must verify after these latest UI changes
- [ ] Rebuild Android APK from updated website and owner app source.
- [ ] Rebuild Windows EXE from updated website and owner app source.
- [ ] Run website JavaScript syntax check and all QA suites.
- [ ] Install APK on a physical Android phone and verify first launch, logo, back navigation, owner website link and share sheet.
- [ ] Launch EXE on a clean Windows account/PC and verify website, owner controls and both downloads.
- [ ] Verify the final APK signature and preserve the local release keystore securely.

## Public website and backend
- [ ] Choose and register a domain; configure DNS and HTTPS.
- [ ] Create a private source repository and connect it to the hosting provider.
- [ ] Deploy the app with a persistent database volume; verify restart, backup and restore.
- [ ] Configure a strong owner account in host secrets; verify public owner login and authorization.
- [ ] Review CSRF protection, secure cookies, session expiry/revocation, rate limiting, audit logs, error handling and monitoring.
- [ ] Publish the APK and EXE at `/downloads/Skillvaya.apk` and `/downloads/Skillvaya.exe`; verify the public links from an external network and on both target device types.
- [ ] Replace local share URLs with the real HTTPS domain. Test sharing on Android and Windows.
- [ ] Test new customer/provider registration, email verification if implemented, sign-in, profile creation, enquiries, reporting and owner moderation.

## PayFast (South Africa, ZAR)
- [ ] Complete PayFast merchant account verification and obtain approved live credentials.
- [ ] Configure secrets only in the hosting environment: mode, merchant ID, merchant key, passphrase, and public HTTPS URL.
- [ ] Keep sandbox mode while testing.
- [ ] Run sandbox checkout and verify ITN reaches `/api/payfast/itn`.
- [ ] Confirm valid complete payments activate the correct listing exactly once; invalid signature, wrong merchant, amount mismatch, cancelled, failed and duplicate notifications do not activate twice.
- [ ] Test partial and full refunds through PayFast's API and verify outcomes in the owner screen.
- [ ] Obtain explicit owner approval before switching the environment to live and taking real money.

## Email and privacy
- [ ] Configure SMTP credentials as host secrets; verify outgoing message delivery and failure handling.
- [ ] Decide whether Gmail inbox sync is needed; implement Google OAuth separately if so.
- [ ] Add privacy notice, retention/deletion process, data export, incident contact and POPIA review.
- [ ] Have South African legal counsel review terms, provider plans, cancellation/refund terms, complaint process and privacy language.

## Launch decision
Do not mark the public launch complete until all required production checkboxes above are tested and evidenced. Do not share loopback URLs such as `127.0.0.1` with customers; those are local-only.
