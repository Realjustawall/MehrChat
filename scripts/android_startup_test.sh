#!/usr/bin/env bash
set -euo pipefail
mkdir -p reports
package=org.mehrchat.mehrchat
component="$package/org.kivy.android.PythonActivity"
apk=$(find bin -name '*x86_64-debug.apk' -print -quit)
adb install -r "$apk"
adb logcat -c
adb shell am start -W -n "$component" | tee reports/android-launch.txt
for index in $(seq 1 30); do
  if adb logcat -d | grep -q 'Start application main loop'; then break;fi
  sleep 1
done
adb logcat -d > reports/android-logcat-startup.txt
if grep -E 'FATAL EXCEPTION|Fatal Python error|Traceback \(most recent call last\)' reports/android-logcat-startup.txt; then exit 1;fi
adb shell pidof "$package" | tee reports/android-pid.txt
grep 'Start application main loop' reports/android-logcat-startup.txt
# The debug-only run-as channel instruments the extracted test app's environment.
# The signed APK itself is unchanged; no owner account or real vault is used.
adb shell am force-stop "$package"
envfile=$(adb shell run-as "$package" find files -name p4a_env_vars.txt | tr -d '\r' | head -n1)
case "$envfile" in files/*/p4a_env_vars.txt) ;; *) echo 'App environment file not found';exit 1;; esac
private_dir=$(adb shell run-as "$package" pwd | tr -d '\r')
result="$private_dir/files/ci-flow.json"
python scripts/android_network_peer.py --config reports/android-network-public.json > reports/android-network-peer.txt 2>&1 &
peer_pid=$!
trap 'kill "$peer_pid" 2>/dev/null || true; wait "$peer_pid" 2>/dev/null || true' EXIT
for index in $(seq 1 30); do
  if [ -s reports/android-network-public.json ]; then break;fi
  sleep 1
done
adb shell "run-as $package sh -c 'cat > files/ci-network.json'" < reports/android-network-public.json

adb shell "run-as $package sh -c 'printf \"\\nMEHRCHAT_SMOKE_TEST=flow\\nMEHRCHAT_SMOKE_RESULT=$result\\nMEHRCHAT_SMOKE_NETWORK_CONFIG=$private_dir/files/ci-network.json\\nMEHRCHAT_SMOKE_SCREENSHOT=$private_dir/files/ci-layout.png\\n\" >> $envfile'"
adb logcat -c
adb shell am start -W -n "$component" >> reports/android-launch.txt
for index in $(seq 1 60); do
  if adb shell run-as "$package" test -f "$result"; then break;fi
  sleep 1
done
adb logcat -d > reports/android-logcat-flow.txt
adb shell dumpsys window windows > reports/android-window-state.txt
if ! adb shell run-as "$package" test -f "$result"; then
  tail -n 120 reports/android-logcat-flow.txt
  exit 1
fi
adb shell run-as "$package" cat "$result" > reports/android-gui-flow.json
adb exec-out run-as "$package" cat "$private_dir/files/ci-layout.png" > reports/android-layout.png
python - <<'PY'
import json
from pathlib import Path
result=json.loads(Path('reports/android-gui-flow.json').read_text())
assert result and all(result.values()) and result.get("tcp_noise_e2ee_request_reply"),result
print('Android encrypted account / Persian chat / group / dialogs / lock / restore: PASS')
PY
printf 'APK installed and shared GUI flows completed on API 35 emulator: PASS\n' >> reports/android-launch.txt
