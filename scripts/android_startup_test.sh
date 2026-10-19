#!/usr/bin/env bash
set -euo pipefail
mkdir -p reports
apk=$(find bin -name '*x86_64-debug.apk' -print -quit)
adb install -r "$apk"
adb logcat -c
adb shell am start -W -n org.mehrchat.mehrchat/org.kivy.android.PythonActivity | tee reports/android-launch.txt
for index in $(seq 1 20); do
  if adb logcat -d | grep -q 'Start application main loop'; then break;fi
  sleep 1
done
adb logcat -d > reports/android-logcat.txt
if grep -E 'FATAL EXCEPTION|Fatal Python error|Traceback \(most recent call last\)' reports/android-logcat.txt; then exit 1;fi
adb shell pidof org.mehrchat.mehrchat | tee reports/android-pid.txt
grep 'Start application main loop' reports/android-logcat.txt
printf 'APK installed, Python/Kivy started, process remains alive: PASS\n' >> reports/android-launch.txt
