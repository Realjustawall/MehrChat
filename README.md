# MehrChat

Persian native messenger for Windows, Linux and Android with self-hosted Windows Server and Ubuntu relays.

- Private chats and owner-managed groups with signed membership history.
- Per-contact Double Ratchet and pinned Noise NK over outbound TCP, with optional verified TLS. The interactive Ubuntu installer always enables TLS, including deployments without a public certificate.
- Password-encrypted local identity, messages, queues and session state.
- Usernames, display names, independently verified fingerprints and encrypted backups.
- Sender expiry, bilateral private-message deletion and encrypted delivery receipts.
- Administrator-controlled encrypted files, disabled by default, up to 4 MiB.
- Five concurrent relays, encrypted offline queues, Persian UI and local Vazirmatn.
- No international runtime service, cloud push provider or external font download.

[Persian setup](README.fa.md) · [Security model](SECURITY.md) · [Build checks](BUILD_STATUS.md) · [GitHub Actions](https://github.com/Realjustawall/MehrChat/actions)

Version **0.2.1-rc1** is independently unaudited. Release APKs require the owner's signing key. Android uninstall requires an external encrypted backup to preserve identity. The interface follows a familiar messenger layout; it is not pixel-identical to Telegram. See `FEATURES.fa.md` for the requirement-by-requirement review, evidence and limits.


## Interactive secure Ubuntu installation

From a source checkout on Ubuntu 24.04, run `sudo bash deploy/install-ubuntu.sh`.
The wizard asks for administrator credentials, shows a locally detected IP for confirmation/correction (enter the public IP for NAT/VPS deployments), accepts an optional domain, and optionally obtains a Let’s Encrypt certificate. You must configure DNS and provider/firewall rules yourself. TCP 80 is needed for HTTP-01 issuance; the relay defaults to TCP 8787. Existing services on port 80 are never stopped automatically.

A private CA and SAN-validated server certificate are always created. Clients trust the exported public CA and the pinned Noise key; certificate verification is never disabled. Public-certificate failure or expiry uses a certificate from the same private CA. A daily systemd timer renews certificates and restarts the relay. Keep the private CA backed up securely; clients must be reconfigured if it is lost or expires. The CA lasts 10 years and private leaves last up to 1 year. Preserve `/var/lib/mehrchat` on upgrades.

Administration remains on `127.0.0.1:8788`; use an SSH tunnel, for example `ssh -L 8788:127.0.0.1:8788 user@server`. The new wizard stores a salted scrypt password verifier and requires both administrator username and password. Legacy installations retain token authentication until configured with the wizard.

The wizard exports `/var/lib/mehrchat/client-profile.json`. Distribute it through a trusted channel. Standard clients show connection setup before login: address, port, Noise pin and TLS/Noise selection. Import the public JSON profile under the profile/certificate section; a successful authenticated probe is required to proceed. Default `127.0.0.1:8787` is a local-server placeholder, not an operated public service. Plain Noise mode remains available for compatible legacy relays and still encrypts transport; TLS mode never silently downgrades.

## Dedicated Windows and Android clients

Install GitHub CLI and authenticate the account allowed to dispatch Actions in this repository. The Ubuntu wizard can request and download dedicated builds, or run:

```sh
python scripts/request-client-build.py /var/lib/mehrchat/client-profile.json
```

Windows runs on Windows; Android runs on Ubuntu in `.github/workflows/dedicated-clients.yml`. Only the validated public profile is embedded. Custom clients automatically test their server and hide endpoint configuration from their interface, showing version, protocol and TLS state. A public certificate is optional, but verified TLS is mandatory for dedicated builds. The endpoint remains discoverable through application inspection and network traffic; hiding it in the UI is not anonymity. A successful workflow provides Windows packages, installable Android debug APKs and an unsigned Android release APK requiring the owner's existing signing key. GitHub Actions requires Internet during the build; the installed application does not require Internet access beyond reachability of its relay.

The interface uses rounded components, a searchable chat list, avatars, date separators, distinct incoming/outgoing bubbles and a responsive desktop/mobile layout. Persian shaping and the bundled Vazirmatn font are retained.
