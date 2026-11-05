#!/bin/bash
set -euo pipefail
MOBILE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="$(dirname "$MOBILE_DIR")"
OUTPUT_DIR="$PROJECT_DIR/work/mobile"
ARCHIVE_DIR="$PROJECT_DIR/artifacts/mobile/1.0.0-3"
mkdir -p "$OUTPUT_DIR" "$ARCHIVE_DIR"
case "${1:-archive}" in
  archive)
    xcodebuild -project "$MOBILE_DIR/ios/App/App.xcodeproj" -scheme App -configuration Release -destination 'generic/platform=iOS' -derivedDataPath "$OUTPUT_DIR/ios-derived" -archivePath "$ARCHIVE_DIR/UACredit-1.0.0-3-unsigned.xcarchive" -jobs 2 CODE_SIGNING_ALLOWED=NO archive > "$OUTPUT_DIR/ios-archive.log" 2>&1
    printf '%s\n' "Unsigned iOS archive: $ARCHIVE_DIR/UACredit-1.0.0-3-unsigned.xcarchive"
    ;;
  simulator)
    xcodebuild -project "$MOBILE_DIR/ios/App/App.xcodeproj" -scheme App -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath "$OUTPUT_DIR/ios-derived" -jobs 2 CODE_SIGNING_ALLOWED=NO build > "$OUTPUT_DIR/ios-simulator.log" 2>&1
    printf '%s\n' "Simulator app: $OUTPUT_DIR/ios-derived/Build/Products/Debug-iphonesimulator/App.app"
    ;;
  *) printf '%s\n' 'Use archive or simulator.' >&2; exit 2 ;;
esac
