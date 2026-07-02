#!/usr/bin/env bash
# Build a distributable zip of the plugin (top-level entry = plugin folder),
# plus a zip of the standalone inf-agent (deployed on the host with your keys).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PLUG="com.ulanzi.infmonitor.ulanziPlugin"
OUT="$ROOT/dist"

cd "$ROOT/$PLUG"
[ -d node_modules/ws ] || { echo "installing ws…"; npm install --omit=dev --no-audit --no-fund; }

# Regenerate the Property Inspector's MDI subset from the canonical Node module
# so the runtime glyphs and the (future) picker can never drift.
node --input-type=module -e "import {MDI_LITE} from './plugin/monitor/mdi-lite.js'; import {writeFileSync} from 'fs'; writeFileSync('property-inspector/mdi-lite.js','// generated from plugin/monitor/mdi-lite.js — do not edit by hand\n// Run pack.sh to regenerate from the canonical Node module.\nwindow.MDI_LITE = '+JSON.stringify(MDI_LITE)+';\n');"

mkdir -p "$OUT"
VER="$(node -p "require('./package.json').version")"
ZIP="$OUT/${PLUG}-${VER}.zip"
rm -f "$ZIP"
cd "$ROOT"
zip -r -q "$ZIP" "$PLUG" -x "*/.DS_Store" "*/npm-debug.log" "*/node_modules/.package-lock.json" "*/.agent-url.json"
echo "built: $ZIP"

# Standalone agent bundle (inf-agent.py + README + systemd unit).
AZIP="$OUT/inf-agent-${VER}.zip"
rm -f "$AZIP"
zip -r -q "$AZIP" agent -x "*/.DS_Store" "*/__pycache__/*" "*.pyc" "*.log"
echo "built: $AZIP"

unzip -l "$ZIP" | tail -n +4 | head -n 26
