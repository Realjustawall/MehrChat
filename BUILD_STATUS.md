# Build and validation

The current commit's GitHub Actions run is authoritative. Packages include actual logs/tests in `reports/`. Workflow source alone does not establish success.

| Target | Required checks |
|---|---|
| Windows 2022 x64 | Security/network tests; native EXE builds; compiled relay bootstrap/E2EE/receipt/deletion test; GUI account creation, Persian chat/group, dialogs, encrypted vault, lock/reopen; installed relay service protocol test |
| Ubuntu 24.04 x64 | Same checks with virtual display; offline systemd installation and protocol test; whole-directory tar preserves runtime symlinks |
| Android arm64-v8a | Debug and unsigned non-debuggable release APK; ABI, pinned versions, 16 KiB alignment, backup/debug and signature checks |
| Android x86_64 | Debug APK checks; install, Python/Kivy startup, full temporary-account GUI flow, real TCP/Noise/E2EE request-reply and layout capture on API 35 emulator |

Physical-device file-provider/keyboard/background behavior, public ACME issuance, production service hardening and real Iranian operator connectivity require separate trials. Shared engine tests use real local TCP, multiple relays and segmented files. No independent audit or owner release signature is supplied. Unsigned APKs require signing before installation; debug APKs are for trials.


Version 0.5.0 adds a real disposable Ubuntu source-installer test: pip/systemd installation, administrator username/password verification, TLS/Noise protocol, renewal timer, private-key permissions and upgrade retention of the server Noise identity and private CA. Windows and Android jobs capture 12 UI screens from temporary accounts. Official publishing requires successful native and Android jobs for the same Git tree, then verifies the externally signed APK's payload, owner certificate and alignment before publishing any release.
