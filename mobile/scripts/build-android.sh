#!/usr/bin/env bash
set -euo pipefail
umask 077

mobile_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(cd "$mobile_dir/.." && pwd)"
android_dir="$mobile_dir/android"
work_dir="$repo_dir/work/mobile"
android_work_dir="$work_dir/android"
artifact_dir="$repo_dir/artifacts/mobile/1.0.0-3/android"
verification_dir="$android_work_dir/verification"
debug_signing_dir="$work_dir/debug-signing"
debug_key="$debug_signing_dir/uacredit-debug.keystore"

export JAVA_HOME="${UACREDIT_JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}"
export ANDROID_HOME="${UACREDIT_ANDROID_SDK:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

if [[ ! -x "$JAVA_HOME/bin/java" || ! -x "$JAVA_HOME/bin/keytool" ]]; then
  printf '%s\n' 'Java 21 is required; set UACREDIT_JAVA_HOME to an installed Java 21 JDK.' >&2
  exit 1
fi
if ! "$JAVA_HOME/bin/java" -version 2>&1 | head -n 1 | grep -Eq 'version "21\.'; then
  printf '%s\n' 'This build is pinned to Java 21. Set UACREDIT_JAVA_HOME accordingly.' >&2
  exit 1
fi
if [[ ! -f "$ANDROID_HOME/platforms/android-36/android.jar" || ! -x "$ANDROID_HOME/build-tools/36.0.0/aapt2" ]]; then
  printf '%s\n' 'Install Android SDK platform 36 and build-tools 36.0.0 in UACREDIT_ANDROID_SDK.' >&2
  exit 1
fi
if [[ ! -f "$android_dir/app/src/main/assets/public/index.html" ]]; then
  printf '%s\n' 'Bundled web assets are missing. Build the mobile web assets and run Capacitor sync first.' >&2
  exit 1
fi

mkdir -p "$artifact_dir" "$verification_dir" "$debug_signing_dir"
chmod 700 "$debug_signing_dir"
if [[ ! -f "$debug_key" ]]; then
  # Android's standard debug identity; never a company, upload, or production key.
  "$JAVA_HOME/bin/keytool" -genkeypair -noprompt \
    -keystore "$debug_key" -storepass android -alias androiddebugkey -keypass android \
    -dname 'CN=Android Debug,O=Android,C=US' -keyalg RSA -keysize 2048 -validity 10000 \
    > "$verification_dir/debug-key-generation.log" 2>&1
fi
chmod 600 "$debug_key"

printf '%s\n' 'Building local-test DEBUG APK and UNSIGNED release AAB. No upload or company key is used.'
cd "$android_dir"
./gradlew --no-daemon --max-workers=2 --no-parallel --console=plain --warning-mode=summary \
  --project-cache-dir "$android_work_dir/project-cache" \
  :app:assembleDebug :app:bundleRelease :app:lintRelease \
  2>&1 | tee "$android_work_dir/build.log"

apk_source="$android_work_dir/gradle-build/app/outputs/apk/debug/app-debug.apk"
aab_source="$android_work_dir/gradle-build/app/outputs/bundle/release/app-release.aab"
apk_output="$artifact_dir/uacredit-1.0.0-3-local-test-debug.apk"
aab_output="$artifact_dir/uacredit-1.0.0-3-release-unsigned.aab"

for artifact in "$apk_source" "$aab_source"; do
  if [[ ! -s "$artifact" ]]; then
    printf 'Missing expected build output: %s\n' "$artifact" >&2
    exit 1
  fi
done
# Keep one authoritative artifact in the work directory; hard links avoid duplicate bytes.
if [[ ! "$apk_source" -ef "$apk_output" ]]; then
  ln -f "$apk_source" "$apk_output"
fi
if [[ ! "$aab_source" -ef "$aab_output" ]]; then
  ln -f "$aab_source" "$aab_output"
fi

"$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --verbose "$apk_output" \
  > "$verification_dir/debug-apk-signature.txt"
"$ANDROID_HOME/build-tools/36.0.0/aapt2" dump badging "$apk_output" \
  > "$verification_dir/debug-apk-badging.txt"
"$ANDROID_HOME/build-tools/36.0.0/zipalign" -c -P 16 -v 4 "$apk_output" \
  > "$verification_dir/debug-apk-zipalign.txt"

python3 - "$android_work_dir" "$apk_output" "$aab_output" <<'PY'
import hashlib
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

work, apk, aab = map(Path, sys.argv[1:])
android = '{http://schemas.android.com/apk/res/android}'
manifest_candidates = list((work / 'gradle-build/app/intermediates/merged_manifests/release').rglob('AndroidManifest.xml'))
if len(manifest_candidates) != 1:
    raise SystemExit(f'Expected one merged release manifest; found {len(manifest_candidates)}')
manifest = ET.parse(manifest_candidates[0]).getroot()
uses_sdk = manifest.find('uses-sdk')
application = manifest.find('application')
assert manifest.get('package') == 'hk.uacredit.app'
assert manifest.get(android + 'versionName') == '1.0.0'
assert manifest.get(android + 'versionCode') == '3'
assert uses_sdk.get(android + 'targetSdkVersion') == '36'
assert application.get(android + 'allowBackup') == 'false'
assert application.get(android + 'usesCleartextTraffic') == 'false'
assert application.get(android + 'debuggable', 'false') == 'false'
permissions = sorted(p.get(android + 'name') for p in manifest.findall('uses-permission'))
allowed_permissions = {
    'android.permission.INTERNET',
    'android.permission.ACCESS_NETWORK_STATE',
    'hk.uacredit.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION',
}
assert set(permissions) <= allowed_permissions, f'Unexpected permissions: {set(permissions) - allowed_permissions}'

native_libs = []
with zipfile.ZipFile(aab) as bundle:
    signatures = [n for n in bundle.namelist() if re.match(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)$', n, re.I)]
    assert not signatures, f'Release AAB must remain unsigned: {signatures}'
    for entry in bundle.namelist():
        if not entry.endswith('.so'):
            continue
        data = bundle.read(entry)
        assert data[:4] == b'\x7fELF', f'Not an ELF native library: {entry}'
        endian = '<' if data[5] == 1 else '>'
        elf64 = data[4] == 2
        if elf64:
            phoff = struct.unpack_from(endian + 'Q', data, 32)[0]
            phentsize, phnum = struct.unpack_from(endian + 'HH', data, 54)
        else:
            phoff = struct.unpack_from(endian + 'I', data, 28)[0]
            phentsize, phnum = struct.unpack_from(endian + 'HH', data, 42)
        aligns = []
        for i in range(phnum):
            off = phoff + i * phentsize
            if struct.unpack_from(endian + 'I', data, off)[0] == 1:
                aligns.append(struct.unpack_from(endian + ('Q' if elf64 else 'I'), data, off + (48 if elf64 else 28))[0])
        native_libs.append({'path': entry, 'elf_load_alignments': aligns, 'supports_16kb_elf_alignment': bool(aligns) and all(a >= 16384 for a in aligns)})
    assert all(lib['supports_16kb_elf_alignment'] for lib in native_libs), 'A native library lacks 16 KB ELF alignment.'

lint_issues = ET.parse(work / 'gradle-build/app/reports/lint-results-release.xml').getroot().findall('issue')
lint_counts = dict(Counter(issue.get('severity') for issue in lint_issues))
assert not any(lint_counts.get(level, 0) for level in ('Error', 'Fatal')), f'Lint errors: {lint_counts}'
evidence = {
    manifest_candidates[0]: work / 'verification/release-merged-manifest.xml',
    work / 'gradle-build/app/reports/lint-results-release.xml': work / 'verification/release-lint.xml',
}
for source, target in evidence.items():
    if target.exists() and source.samefile(target):
        continue
    if target.exists():
        target.unlink()
    os.link(source, target)
report = {
    'package': 'hk.uacredit.app',
    'version_name': '1.0.0',
    'version_code': 3,
    'target_sdk': 36,
    'compile_sdk': 36,
    'release_signing': 'unsigned',
    'debug_signing': 'app_specific_local_test_key_only',
    'permissions': permissions,
    'allow_backup': False,
    'cleartext_traffic': False,
    'release_lint_severity_counts': lint_counts,
    'retained_manifest': str(work / 'verification/release-merged-manifest.xml'),
    'retained_lint_report': str(work / 'verification/release-lint.xml'),
    'debug_apk_signature_verified': True,
    'debug_apk_zipalign_16kb_check_passed': True,
    'native_libraries': native_libs,
    'native_library_16kb_scope': 'No packaged .so libraries' if not native_libs else 'ELF LOAD alignment inspected; generated split APK ZIP alignment and device runtime still require verification',
    'device_runtime_16kb_test': 'not_run_by_build_script',
    'store_upload': 'not_performed',
    'artifacts': [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (apk, aab)],
}
(work / 'verification/build-verification.json').write_text(json.dumps(report, indent=2) + '\n')
(apk.parent / 'SHA256SUMS').write_text(''.join(f'{a["sha256"]}  {Path(a["path"]).name}\n' for a in report['artifacts']))
print(json.dumps(report, indent=2))
PY

printf '\n%s\n' 'Complete: APK is for local testing only; AAB remains unsigned and cannot be uploaded as a release.'
