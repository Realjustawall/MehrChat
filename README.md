# MehrChat

MehrChat is a self-hosted native messenger for Windows, Linux and Android. It provides private conversations, groups, encrypted attachments, delivery receipts, message expiry and encrypted identity backups. The interface supports Persian and English, selectable before login, with light/dark themes and the bundled Vazirmatn font. These installation instructions are in English.

**Version 0.7.0.** Download application packages from [Releases](https://github.com/Realjustawall/MehrChat/releases). Builds and test reports are available in [GitHub Actions](https://github.com/Realjustawall/MehrChat/actions). Read the [security model](SECURITY.md) before operating a server. No independent security audit is claimed.

## Choose your installation

| Package | Purpose | Installation |
| --- | --- | --- |
| `MehrChat-Windows-x64.zip` | Windows desktop client and Windows relay | Extract the complete archive; use the instructions below. |
| `MehrChat-Ubuntu-x64.tar.gz` | Linux desktop client and compiled relay | Extract the complete archive; use the desktop or legacy relay instructions below. |
| `MehrChat-0.7.0-Android-arm64-v8a.apk` | Signed Android release for modern 64-bit ARM phones | Install the APK and configure your server. |
| `MehrChat-0.7.0-Server-Source.tar.gz` | Interactive Ubuntu TLS installer and server source | Recommended server deployment. |
| `MehrChat-0.7.0-UI-Screenshots.zip` | Actual Windows and Android emulator UI captures | Extract to view connection, login, conversations and settings. |
| `SHA256SUMS.txt` | Download checksums | Check your downloaded files before installation. |

Windows executables are not Authenticode-signed. Android test/debug APKs and unsigned APKs in Actions are development artifacts; use the signed release APK for normal installation. The Android emulator test runs on x86_64; the phone release is arm64-v8a. Physical-device behavior still needs device-specific trials.

### Verify downloads

On Windows, run `Get-FileHash .\MehrChat-Windows-x64.zip -Algorithm SHA256` in PowerShell and compare the value with `SHA256SUMS.txt`. On Linux, put the checksum file beside the downloaded assets and run:

```sh
sha256sum --ignore-missing -c SHA256SUMS.txt
```

All checked files must report `OK`. The release also publishes `Android-signature-verification.txt` with the APK certificate SHA-256 fingerprint; compare it with `apksigner verify --print-certs your.apk` if Android SDK build-tools are installed.

## Language, appearance and writing

Choose **فارسی / English** and **Light / Dark** on the connection or login screen. After login, open **Menu → Appearance and language** to change the language, theme, text size or Enter behavior. Preferences are public local UI settings; no password, keys or server profile is stored in that preferences file. Theme/language changes preserve the current draft and connection fields.

The Vazirmatn font is used for labels, dialogs, inputs and password hints. Logical text is wrapped before Persian shaping and bidirectional layout. Messages and captions keep the original Unicode; emoji family/profession ZWJ sequences are not split by bidi processing. Shift+Enter makes a new line when Enter-to-send is enabled; otherwise Enter makes a new line. Message actions include reply, copy and deletion under existing group permissions.

The offline picker includes **3,944 canonical Emoji 17.0 sequences** using Twemoji 17.0.3, including skin tones, flags and families. It supports categories, English name search, skin-tone filters, pagination and recently used items. No network connection is used to render emoji.

## Encrypted attachments and safe previews

Attachments remain capped at **4 MiB** and require the administrator to enable file transfer. Choose a file, inspect its preview, add a multiline caption, then send. Image thumbnails, video cover frames, audio waveform/metadata, captions and replies are inside the same authenticated E2EE payload as the attachment. A SHA-256 digest additionally checks the original bytes at receive/export. The relay sees ciphertext and bounded routing records; it does not extract archives, run antivirus, decode images/media or execute uploaded files.

Automatic received previews contain only an explicitly validated, **uncompressed RGB** raster (maximum 256×256) or at most 64 numeric waveform values. The receiver does not feed the original attachment into an image/video/audio codec for automatic preview. Opening a preview displays the sanitized raster/waveform; this is not full-resolution original viewing or full media playback. Originals are saved only through an explicit file-picker action, never auto-opened.

Preview generation for an explicitly selected local file runs separately from the account:

- **Windows:** a dedicated executable runs in a no-network-capability AppContainer, with access only to its worker executable and private sandbox temporary directory. A kill-on-close job limits memory, CPU and child processes. Use the normal per-user installation; preview generation fails closed if its worker ACL/profile cannot be created. Source Python execution does not bypass this requirement.
- **Android:** a non-exported `isolatedProcess` service has a distinct UID and no app permissions. Input crosses a bounded pipe; output is only bounded raw RGB or waveform metadata. The caller kills the isolated process after completion or timeout. Video frame extraction requires Android 8.1/API 27 or newer; Android 8.0 can still send/save the original attachment.
- **Linux:** the image worker preloads codecs, drops new privileges and installs seccomp rules denying filesystem opens/mutations, network, process creation and process inspection. Video/audio codecs additionally require `bubblewrap` and private filesystem/network namespaces; install `bubblewrap` and `libseccomp2` from your distribution. If the host disables these facilities, the app sends the attachment without generating a preview. There is no unsandboxed fallback.

Generation has byte/pixel/time limits; images larger than 12 megapixels are refused. Supported original formats are limited to ordinary JPEG/PNG/GIF/WebP, MP4-family video and common audio formats detected by content, not filename. A video preview is one cover frame. Waveforms cover the first 30 seconds at most; duration may be the preview duration on desktop. GIF previews are static. SVG/HTML/PDF, archives and executables are never previewed.

Encryption and sandboxing do **not** certify that an original file is virus-free. A server cannot virus-scan encrypted content without breaking this privacy model. Decoder, OS and sandbox vulnerabilities remain possible; keep the OS and dependencies updated. Treat exported originals as untrusted when opening them in other applications. See SECURITY.md for the boundary and residual risks.

## Contact QR and short addresses (0.6.0)

Open **Menu → My QR and ID**. Every existing or new identity has a stable **12-digit ID** and a **5-letter share code** (A–Z). Both remain unchanged when you edit your display name or username, change the vault password, or restore the same identity from backup. The share code is public invitation information, **not your account password or a login credential**.

To add someone, open **+ → New contact** and either:

- Enter their 12-digit ID and 5-letter share code, then check and confirm the displayed name. Persian digits, spaces in the ID and lowercase share letters are accepted. Both users must have registered with a common **0.6.0 relay** at least once. The recipient can be offline after registration.
- Scan their QR with the camera, open an existing QR image, or paste their contact link. The signed public identity card is checked and the form fills automatically. Confirm before adding. QR exchange works without a directory lookup or internet connection; delivering messages still requires a reachable relay.

Camera access is requested only when scanning. Images and camera frames are processed locally. Close the scanner to release the camera; if the camera is absent or permission is denied, use a QR image or the manual ID/code. Never enter a vault/account password in this form.

The ID and share code are derived from the public key fingerprint and checked on the client, so an unrelated relay-supplied identity is rejected. This short identifier is a convenience check with less entropy than the full fingerprint. For sensitive conversations, exchange the full QR directly or verify the full identity fingerprint through a trusted channel. Sharing a QR also shares your public name, username and public keys, never private keys.

Upgrade the relay for short-address search. Its existing `users` database is migrated in place to store signed **public** identity cards and addresses. Private keys remain on client devices. Older clients can still use their signed identity-card/fingerprint workflow.

## Interface and licenses

Desktop and Android use the same responsive native interface with a Telegram Web inspired light layout, pixel-measured Persian/English wrapping, compact scrollable dialogs, offline color emoji, and a camera/QR contact flow. The Windows interface remains native; it does not log into Telegram or load a remote website. Toolbar icons and the chat wallpaper are adapted from **Telegram Web A** (`Ajaxy/telegram-tt`, commit `f67a40879a7d78c2683ec5a296cf55bc22417d56`), with the converted font and provenance bundled in `assets/telegram-source.txt`. This version is distributed under **GPL-3.0**; see `LICENSE` and `assets/licenses/Telegram-Web-GPL-3.0.txt`.

Emoji graphics are **Twemoji 17.0.3**, © Twitter and contributors, **CC-BY-4.0**; see `assets/licenses/Twemoji-graphics-LICENSE.txt`. The in-app About screen includes attribution. No Telegram logo, Telegram service integration or affiliation is implied.

## 1. Deploy a secure Ubuntu server

### Requirements

- Ubuntu 24.04 x64 with `sudo`, systemd and a reachable IPv4 or IPv6 address.
- Internet access during initial installation to obtain OS/Python dependencies. Runtime chat only needs connectivity between clients and the relay.
- TCP **8787**, or your chosen relay port, reachable through the server and hosting-provider firewalls. For a server behind NAT, forward this TCP port to the server.
- An optional domain whose DNS points to the server. Let’s Encrypt HTTP-01 issuance needs public TCP **80**. Existing services on port 80 are never stopped automatically.
- Never expose management TCP **8788** to the network; administration is loopback-only.

### Download and run

Download `MehrChat-0.7.0-Server-Source.tar.gz` from the release and verify its checksum. Then:

```sh
tar -xzf MehrChat-0.7.0-Server-Source.tar.gz
cd MehrChat-0.6.0
sudo bash deploy/install-ubuntu.sh
```

Alternatively, use a source checkout:

```sh
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/Realjustawall/MehrChat.git
cd MehrChat
git checkout v0.6.0
sudo bash deploy/install-ubuntu.sh
```

The wizard performs these steps:

1. Ask for the administrator username and password. The password must contain at least 14 characters and must be entered twice. A salted scrypt verifier is stored, not the password itself.
2. Display an IP detected from local interfaces. Confirm it or replace it with the public/reachable IP. Automatic discovery cannot infer a provider NAT mapping.
3. Ask for an optional domain; press Enter to use the IP directly. Configure DNS yourself before requesting a public certificate.
4. Ask for the relay TCP port, default `8787`. Port `8788` is reserved for local administration.
5. Create a persistent private CA and a server certificate covering the confirmed IP and optional domain. Verified TLS is enabled even when no domain/public certificate is used.
6. Optionally request a Let’s Encrypt certificate. If issuance fails, retain TLS with the private CA. Client certificate verification is never disabled.
7. Install and start `mehr-relay.service`, set up daily certificate maintenance, verify the local TLS/Noise listener and export the **public** connection profile.
8. Build and download dedicated Windows/Android clients through GitHub Actions (enabled by default; choose `n` to skip). The wizard installs GitHub CLI and offers device-code login when needed. See the dedicated-build section below.

Open the relay port in your provider firewall. If UFW is already enabled, allow your SSH port before applying any firewall changes, then permit the selected relay port:

```sh
sudo ufw allow 8787/tcp
# Only if requesting/renewing a public HTTP-01 certificate:
sudo ufw allow 80/tcp
```

These commands do not enable UFW or replace provider-side firewall/NAT configuration.

### Verify and administer

```sh
sudo systemctl is-active mehr-relay
sudo systemctl status mehr-relay --no-pager
sudo journalctl -u mehr-relay -n 100 --no-pager
sudo systemctl list-timers mehr-tls-renew.timer
sudo cat /var/lib/mehrchat/client-profile.json
```

The exported profile contains the host, port, pinned public Noise key, transport mode and public CA certificate. Share it through a trusted channel; replacing this profile can redirect a client to another server. Never distribute `transport-key.json`, `tls/ca-key.pem`, `tls/server-key.pem`, `admin-credentials.json` or any signing key.

To open administration from another computer, run this on that computer:

```sh
ssh -N -L 8788:127.0.0.1:8788 ubuntu@YOUR_SERVER_IP
```

Keep the SSH session running, open `http://127.0.0.1:8788` in your local browser, and enter the administrator username/password selected during setup. You can enable encrypted file transfer here; it is disabled by default and limited to 4 MiB per file.

### Certificates, upgrades and backups

TLS encrypts both directions. Noise authenticates the pinned server key inside that transport, and message encryption is a separate end-to-end layer. If public-certificate renewal fails or the public certificate expires, daily maintenance uses a valid certificate signed by the same private CA. Clients load the bundled Mozilla CA store in addition to available OS roots and the profile’s private CA. This also supplies public-certificate trust on embedded Android Python runtimes. No automatic plaintext downgrade or unverified-certificate bypass is provided.

Experimental installer versions that omitted X.509 key identifiers need a one-time CA certificate metadata update for strict Android/Python TLS. Rerunning setup preserves the private CA key, issuer and validity, saves the previous public certificate as `tls/ca-legacy.pem`, and exports an updated public profile. Redistribute that profile and rebuild dedicated clients that embedded the previous certificate. Certificate verification is never disabled.

The private CA lasts 10 years; private server certificates last up to 1 year and are renewed before expiry. Reconfigure clients before the CA expires. Replacing or losing the CA/Noise identity requires redistributing trusted profiles and rebuilding dedicated clients. TLS renewal restarts the relay; clients reconnect automatically.

Back up `/var/lib/mehrchat` securely, including `tls/`, before upgrading. This directory contains the server transport identity, administrator verifier, queued encrypted messages, configuration and private certificate keys. It does **not** contain client E2EE private keys. Install updated source in a separate directory and rerun the installer; confirm reconfiguration only when intended. Preserve the original data directory and compare the public Noise pin/CA before and after the upgrade.

For manual maintenance:

```sh
sudo systemctl restart mehr-relay
sudo systemctl start mehr-tls-renew.service
sudo journalctl -u mehr-tls-renew.service -n 100 --no-pager
```

To stop the installation without deleting its data:

```sh
sudo systemctl disable --now mehr-tls-renew.timer mehr-relay
```

## 2. Install the Windows client

1. Download and fully extract `MehrChat-Windows-x64.zip`. Keep the entire `dist/MehrChat` directory together; the EXE needs its bundled runtime.
2. Open PowerShell in the extracted `MehrChat-Windows-x64` directory and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-windows-client.ps1
```

This installs the client under `%LOCALAPPDATA%\Programs\MehrChat` and creates a desktop shortcut. It does not need Administrator privileges. You can also run `dist\MehrChat\MehrChat.exe` directly from the extracted package.

The encrypted account lives under `%APPDATA%\MehrChat\identity.mcv`. Before upgrading, create an encrypted backup in the application. Close the client, extract the new package separately and rerun its installer. Do not delete the account data directory.

To remove installed application files while preserving the account:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\uninstall-windows-client.ps1
```

## 3. Install the Android client

Download `MehrChat-0.7.0-Android-arm64-v8a.apk` to a compatible Android phone (Android 8/API 26 or newer, 64-bit ARM). Open the APK and, if Android requests it, allow installation from the download source you chose. Verify the release checksum and signing certificate fingerprint against the published release information.

For an existing installation, install the new APK over it. Android updates require the **same signing certificate** and a compatible version code. A debug APK uses another key and may not update to the official APK. Export an encrypted backup first; uninstalling Android deletes the local app identity and keys. If an installation reports a signature conflict, do not uninstall until the backup has been exported and its password retained.

Create and save the prompted encrypted backup outside the app. Without it and its password, deleting the app or losing the phone can permanently lose the identity. The app needs the Internet permission for relay networking; it does not depend on Firebase or a cloud push account.

## 4. Connect and create an account

1. Obtain the public `client-profile.json` from your administrator through a trusted channel.
2. Start the standard client. The first screen lets you set the **server address**, **port**, **Noise public pin** and **connection type**. The default `127.0.0.1:8787` is a local-server placeholder, not a hosted public service.
3. Open the profile/certificate section, paste the public JSON profile and choose the import button. This also supplies the private CA certificate when needed. Alternatively, enter all fields manually. Select **TLS + Noise** for the interactive Ubuntu installation. Explicit **Noise** mode is for legacy relays that do not use TLS; it remains encrypted but is incompatible with a TLS-only listener.
4. Choose the connection-check/continue button. The client must verify TLS (when selected), the pinned Noise key and relay protocol before showing login. A failure keeps you on the connection screen.
5. Create a local account using a username, display name and vault password, or unlock your existing account. Retain the vault password and create the encrypted backup.
6. Add a contact by exchanging identity cards and independently checking fingerprints. Username search can find live relay users but does not independently establish identity. Use a separate trusted channel to verify the fingerprint before importing a contact.
7. Create a group, select participants and send messages. Files are available only when enabled by every connected relay. Expiry and deletion instructions require peers to run compatible clients; a recipient can still retain a copy outside the application.

The vault password unlocks local encrypted data; it is not a server administrator credential. Keep backup passwords separate from server administration credentials.

## 5. Dedicated Windows/Android builds

Dedicated clients embed the validated **public** server profile, automatically test that server and hide endpoint settings from the UI. Users see application version, protocol and TLS information. This hides configuration from casual UI viewing; network traffic and program inspection can reveal the endpoint. Dedicated builds require verified TLS.

Build prerequisites on the machine requesting builds:

- GitHub CLI (`gh`) installed and authenticated to the GitHub account allowed to run Actions in this repository (or your fork).
- GitHub Actions enabled, with available runner minutes and artifact storage.
- Internet access during compilation/download. Windows builds run on Windows runners; Android builds run on Ubuntu runners. Ubuntu does not cross-compile a Windows EXE locally.

When using the installed Ubuntu wizard, authenticate `gh` in the same account/environment that runs the request, or supply an appropriately scoped `GH_TOKEN` in that process. Do not put the token in a connection profile. A normal user's CLI login is not automatically available under `sudo`.

From a source checkout with server dependencies installed:

```sh
gh auth login
python scripts/request-client-build.py /path/to/client-profile.json \
  --repo Realjustawall/MehrChat --ref main --output dedicated-clients
```

The secure installer offers this request by default after the relay passes its TLS/Noise health check. It installs `gh` and offers browser/device-code authentication in the same account that runs setup. If authentication or a build fails, the verified relay keeps running and setup prints an exact resume command. Downloaded artifacts are stored in `/var/lib/mehrchat/dedicated-clients`. It waits for the exact requested Actions run and downloads its artifacts. The profile, CA certificate and Noise pin are public deployment configuration; no server private key or administrator password is sent. Custom builds contain installable **test/debug** APKs and an **unsigned** Android release APK. Sign the latter with your own existing deployment signing key before distribution. The main project's signing key is never embedded in the source or automatically supplied to custom builds.

## 6. Linux desktop and legacy relay packages

For the Linux desktop client, fully extract `MehrChat-Ubuntu-x64.tar.gz`, enter the extracted directory and run:

```sh
bash deploy/install-linux-client.sh
```

The client is installed under `${XDG_DATA_HOME:-$HOME/.local/share}/MehrChatApp`. A menu entry is created. Run `bash deploy/uninstall-linux-client.sh` to remove it while preserving the encrypted identity under `~/.local/share/MehrChat` (unless `APPDATA` was explicitly configured).

The compiled legacy relay installers are `sudo bash deploy/install-ubuntu-offline.sh` and, on Windows in an elevated PowerShell, `deploy/install-windows-relay.ps1`. They install the included compiled relay without pip. **These legacy installers do not configure TLS**: their default connection type is Noise, their management credential is initially `admin-token.txt`, and they are not replacements for the secure interactive Ubuntu installer.

Manual relay execution supports explicit certificate files:

```sh
./dist/MehrRelay --host 0.0.0.0 --port 8787 --data relay-data \
  --tls-cert /absolute/path/server.pem --tls-key /absolute/path/server-key.pem
```

Use `dist\MehrRelay.exe` on Windows. Provide clients with the matching public CA/Noise profile. Manual certificate renewal, data protection and firewall configuration are the operator's responsibility.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Connection check fails | Reachable IP/domain, DNS, provider firewall, NAT forwarding, selected TCP port, TLS/Noise mode and server service status. |
| TLS verification fails | Correct hostname/IP in the certificate, device clock, trusted public profile/CA, certificate validity. Never disable verification. |
| Noise pin fails | Confirm the server identity through a trusted channel. A server data reset can change its pin. |
| Public certificate request fails | DNS points here, TCP 80 reachable, no conflicting listener, ACME availability/rate limits. Private-CA TLS remains enabled. |
| Local admin page is unavailable | Keep the SSH tunnel open and check `mehr-relay` logs. Do not expose port 8788 publicly. |
| Duplicate username | Choose another username; the relay enforces uniqueness. |
| Files disabled | Ask the relay administrator to enable files; every connected relay must allow them. |
| Dedicated build cannot dispatch | Check `gh auth status`, repository/ref, Actions permissions, runner quota and that the workflow exists on the default branch. |
| Android signature conflict | Export a backup first and compare signing certificates; debug and official keys differ. |
| Windows client fails to launch | Extract the whole package and keep all runtime files. Inspect reports attached to the release. |

## Build and validation

For development, use Python 3.12 and `python -m pip install -r requirements.txt`. Run `python -m unittest discover -s tests -v`. Native packaging uses `python scripts/build.py client` and `python scripts/build.py server` with PyInstaller installed; Windows builds need the graphics dependencies specified in the workflow. Android builds use `buildozer.spec` and the pinned local recipes. Do not substitute untested cryptography/native versions into an existing Android cache.

CI validates protocol/security tests, authenticated TLS connection gating, compiled client/relay execution, installation/uninstallation, server identity retention, Android ABI/16-KiB alignment/backup/debug settings and Android emulator GUI plus real TLS/Noise/E2EE network exchange. UI galleries are captured from temporary test accounts in the compiled Windows client and Android emulator, not generated mockups. Physical Android devices, real public ACME provisioning and operator-specific network reachability need deployment trials.
