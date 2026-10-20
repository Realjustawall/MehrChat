# Security scope — 0.2.1-rc1

This integration has not received an independent cryptographic audit. Tests demonstrate selected behaviors, not a security proof or production certification. Trusted endpoints and independent fingerprint comparison are required.

Identity: device-generated Ed25519 signing key and independent Curve25519 key. SHA-256 fingerprint binds both public keys. User private keys, passwords and ratchet secrets never go to the relay. Public cards are online memory only; username/fingerprint reservations persist.

Bootstrap: application-specific signed interactive ephemeral X25519 exchange, transcript-bound HKDF-SHA256 and initial encrypted key confirmation. Deterministic initiator selection and authenticated generations coordinate reset/recovery. Bootstrap private material is discarded after establishment. First contact requires both devices to participate. This composition requires independent review.

Messages: DoubleRatchet 1.3.0, recommended X25519 / HKDF-SHA256 / separate HMAC chains and ChaCha20-Poly1305 adapter binding envelope and ratchet header. Skipped keys are bounded to 1000, with no time-based pruning yet. This is not the full Signal Protocol, PQXDH, MLS, post-quantum encryption or deniable messaging. Legacy SealedBox is accepted only for signed bootstrap controls, never application content.

Transport: Noise_NK_25519_ChaChaPoly_SHA256 with pinned server X25519 key, ephemeral transport keys and client signature over handshake hash. No TLS/plaintext fallback. Pin distribution must be trusted. Server transport keys cannot decrypt E2EE payloads. Protocol/pins are incompatible with v0.1.

Storage: Argon2id MODERATE (3 operations, 256 MiB), random salt and SecretBox for the whole client state. Mandatory minimum 12-character password, atomic writes, fsync and exclusive GUI vault lock. Transactions restore ratchet state and identity aliases after validation/disk errors. Python cannot guarantee zeroization or protection against a privileged OS attacker. Secrets exist in memory while unlocked. Backups retain their original password and may contain old history/keys. One active installation per identity is supported.

Groups: up to 32 members and 64 creator-signed membership epochs, with accepted-prefix verification. Stale/forked membership is rejected. Group-scoped card introduction relies on the creator and never verifies a private contact. Independent pairwise ratchets encrypt fanout; removed members are excluded from future sends by conforming clients. Prior content remains theirs. There is no relay-accessible group decryption key.

Deletion: authenticated events/local tombstones and sender-signed retraction capabilities. Only original sender/recipient can purge a delivery envelope. Relay tombstones bind id, sender and recipient, preventing a capability for another route from suppressing a foreign message. Private participants may delete either side's messages; group participants may delete only their own. Tombstones last up to 90 days; normal TTL at most 30 days. Upper relay bounds allow five minutes clock skew. External copies, screenshots, malicious clients/relays, old backups and physical flash remnants cannot be remotely erased.

Visible relay metadata: IP, timing, size, sender/recipient identifiers, kind and expiry. Dropping, delaying and denial of service remain possible; this is not anonymous messaging. Limits: 2000 envelopes / 64 MiB per recipient, 1 GiB queue, 64 connections, 20 requests/sec and burst 120. File names reject traversal, device names, alternate streams and bidi override characters before commit/export defaults. Files default off, up to 4 MiB; logical records 16 MiB; encrypted relay envelopes at most 12 MiB for files and 4 MiB otherwise, allowing the maximum signed group history and encoding overhead; quarantine 100 envelopes / 16 MiB. Group fanout/full-vault serialization limit scale; no sustained-load certification exists.

Admin HTTP is loopback-only with random token. Never expose it publicly. The message listener intentionally binds public interfaces; use supplied service permissions and host firewall. Multi-relay usernames are independent. Background push, multi-device sync, calls and large-file streaming are outside this version.

Desktop uninstallation preserves the external vault path. Android uninstall deletes private data: an explicit external encrypted backup is required. No recovery backdoor exists.

Backup restoration authenticates and validates basic account structure before publication, takes the destination account's exclusive lock and retains it for the restored session. Existing accounts are never overwritten. A failed password attempt releases its lock explicitly. Desktop backup export uses exclusive creation and removes partial output on write failure. Password changes invalidate the backup reminder marker; old backups retain their old password. Encrypted per-chat drafts are isolated when switching recipients and saved before lock. File export rechecks the live account, message existence and expiry after the document picker returns.

Backup export and restore share a 1 GiB limit; export rejects larger snapshots rather than creating an unsupported backup. The whole-vault format still requires enough RAM for encoding, decryption and the decoded state. Large histories and group fanout can exceed practical mobile memory limits; the size bound is not a claim that every phone can restore a 1 GiB account.

Release gates: independent review, physical Android/native target tests, domestic cross-operator trials, abuse/load testing and owner-controlled signing. APK inspection checks pinned versions, foreign-architecture libraries, 16 KiB ELF alignment and backup/debug settings. Emulator startup is separate from physical-device validation.

References: https://signal.org/docs/specifications/doubleratchet/ ; https://python-doubleratchet.readthedocs.io/ ; https://noiseprotocol.org/noise.html ; https://pynacl.readthedocs.io/
