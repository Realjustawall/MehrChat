#!/usr/bin/env bash
set -euo pipefail
[ "$#" = 4 ] || { echo 'Usage: sign_android.sh unsigned.apk keystore.jks alias signed.apk';exit 2; }
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT}"
: "${MEHRCHAT_KEYSTORE_PASSWORD:?Set MEHRCHAT_KEYSTORE_PASSWORD}"
[ ! -e "$4" ] || { echo 'Output already exists.';exit 2; }
tools="$(find "$ANDROID_SDK_ROOT/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -n1)"
aligned="$(mktemp --suffix=.apk)";trap 'rm -f -- "$aligned"' EXIT
"$tools/zipalign" -f -P 16 4 "$1" "$aligned"
"$tools/apksigner" sign --ks "$2" --ks-key-alias "$3" --ks-pass env:MEHRCHAT_KEYSTORE_PASSWORD --out "$4" "$aligned"
"$tools/apksigner" verify --verbose --print-certs "$4"
