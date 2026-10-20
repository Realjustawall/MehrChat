# MehrChat

Persian/English native messenger for Windows, Linux and Android with self-hosted Windows Server and Ubuntu relays.

- Private chats and owner-managed groups with signed membership history.
- Per-contact Double Ratchet and pinned Noise NK over outbound TCP, without TLS certificates.
- Password-encrypted local identity, messages, queues and session state.
- Usernames, display names, independently verified fingerprints and encrypted backups.
- Sender expiry, bilateral private-message deletion and encrypted delivery receipts.
- Administrator-controlled encrypted files, disabled by default, up to 4 MiB.
- Five concurrent relays, encrypted offline queues, Persian/English UI and local Vazirmatn.
- No international runtime service, cloud push provider or external font download.

[Persian setup](README.fa.md) · [Security model](SECURITY.md) · [Build checks](BUILD_STATUS.md) · [GitHub Actions](https://github.com/Realjustawall/MehrChat/actions)

Version **0.3.0-rc1** is independently unaudited. Release APKs require the owner's signing key. Android uninstall requires an external encrypted backup to preserve identity. The interface follows a familiar messenger layout; it is not pixel-identical to Telegram. See `FEATURES.fa.md` for the requirement-by-requirement review, evidence and limits.

Security hardening in 0.3.0 includes required local SOCKS5 mode with proxy-side destination DNS and no direct fallback, Android secure-screen/overlay protection, configurable 30/60/300-second idle lock (default 60), padded Noise records, bounded relay admission/registration/retraction state, and UI text/undo cleanup on lock. The relay admin page is also available in Persian and English.

The proxy is supplied and operated by the user; Tor is not bundled or started automatically. Direct mode remains available for domestic/offline networks. This is not an anonymity guarantee or protection against a compromised OS.
