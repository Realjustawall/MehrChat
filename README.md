# MehrChat

Persian native messenger for Windows, Linux and Android with self-hosted Windows Server and Ubuntu relays.

- Private chats and owner-managed groups with signed membership history.
- Per-contact Double Ratchet and pinned Noise NK over outbound TCP, without TLS certificates.
- Password-encrypted local identity, messages, queues and session state.
- Usernames, display names, independently verified fingerprints and encrypted backups.
- Sender expiry, bilateral private-message deletion and encrypted delivery receipts.
- Administrator-controlled encrypted files, disabled by default, up to 4 MiB.
- Five concurrent relays, encrypted offline queues, Persian UI and local Vazirmatn.
- No international runtime service, cloud push provider or external font download.

[Persian setup](README.fa.md) · [Security model](SECURITY.md) · [Build checks](BUILD_STATUS.md) · [GitHub Actions](https://github.com/Realjustawall/MehrChat/actions)

Version **0.2.1-rc1** is independently unaudited. Release APKs require the owner's signing key. Android uninstall requires an external encrypted backup to preserve identity. The interface follows a familiar messenger layout; it is not pixel-identical to Telegram. See `FEATURES.fa.md` for the requirement-by-requirement review, evidence and limits.
