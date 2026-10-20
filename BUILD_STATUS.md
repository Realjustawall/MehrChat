## 0.4.0-rc1 verification

106 source tests passed locally, including actual TLS + Noise discovery, pin rejection, SOCKS remote DNS, independent group verification and the wizard public-certificate failure path. The local dedicated-APK signing helper generated a disposable key and signed/verified a real APK. Native CI now exercises the compiled relay over TLS and pre-login standard/dedicated connection screens. Android network smoke now uses TLS + Noise. Check the current Actions run for platform build results; source tests alone do not establish them. No real deployment domain or operator account has been supplied for ACME issuance or personalized production builds.

# Build and validation

The current commit's GitHub Actions run is authoritative. Packages include actual logs/tests in `reports/`. Workflow source alone does not establish success.

| Target | Required checks |
|---|---|
| Windows 2022 x64 | Security/network tests; native EXE builds; compiled relay bootstrap/E2EE/receipt/deletion test; GUI account creation, Persian chat/group, dialogs, encrypted vault, lock/reopen; installed relay service protocol test |
| Ubuntu 24.04 x64 | Same checks with virtual display; offline systemd installation and protocol test; whole-directory tar preserves runtime symlinks |
| Android arm64-v8a | Debug and unsigned non-debuggable release APK; ABI, pinned versions, 16 KiB alignment, backup/debug and signature checks |
| Android x86_64 | Debug APK checks; install, Python/Kivy startup, full temporary-account GUI flow, real TCP/Noise/E2EE request-reply and layout capture on API 35 emulator |

Physical-device file-provider/keyboard/background behavior, production service hardening and real Iranian operator connectivity require separate trials. Shared engine tests use real local TCP, multiple relays and segmented files. No independent audit or owner release signature is supplied. Unsigned APKs require signing before installation; debug APKs are for trials.

0.3.0 adds regression tests for SOCKS destination-DNS isolation, proxy failure without direct fallback, authenticated Noise and E2EE over the proxy, quota rollback, bounded admission state, translation coverage, Android protection acknowledgement and language persistence. Compiled GUI flows run in both Persian and English and check switching languages without moving or losing drafts. Emulated Android flows also assert secure-screen initialization. These checks do not certify Tor anonymity, hardware-backed key protection, physical keyboard compatibility or production readiness.

0.3.1 adds 10 adversarial group regressions and a live viewport matrix for both languages, list/chat modes and four desktop-hosted viewport sizes. Android runs the same geometry assertions at the emulator's actual viewport. The tests assert mounted-pane and control bounds, preventing nonempty but clipped screenshots from passing. Actual build success is determined by the linked run.
