#!/bin/sh
# Builds ~/Desktop/CLOUDS.app: a double-clickable launcher for
# ./run_clouds_ui.sh, for operators who don't want a terminal.
#
# It opens Terminal.app and runs the real launcher there (not a bare Qt
# process) on purpose - first-run venv setup and any crash need to stay
# visible, not vanish with the app the moment something goes wrong.
#
#   ./create_desktop_icon.sh              build/refresh the icon
#
# macOS only. Re-run any time after moving the repo - the app embeds this
# repo's current absolute path at build time, it does not discover it later.
set -e

[ "$(uname -s)" = "Darwin" ] || {
    printf '%s\n' "create_desktop_icon.sh: macOS only." >&2
    exit 1
}

REPO="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Desktop/CLOUDS.app"
LOGO="$REPO/assets/clouds_logo.png"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/MacOS/CLOUDS" <<EOF
#!/bin/sh
osascript <<APPLESCRIPT
tell application "Terminal"
    activate
    do script "cd \\"$REPO\\" && ./run_clouds_ui.sh; echo; echo '[CLOUDS UI exited]'; exec \\\$SHELL"
end tell
APPLESCRIPT
EOF
chmod +x "$APP/Contents/MacOS/CLOUDS"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>CLOUDS</string>
    <key>CFBundleDisplayName</key>
    <string>CLOUDS Spectral Engine</string>
    <key>CFBundleIdentifier</key>
    <string>de.bexus.clouds-ui</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>CLOUDS</string>
    <key>CFBundleIconFile</key>
    <string>CLOUDS.icns</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# The logo is a wide wordmark, not a square mark - pad it onto a transparent
# square first so icns doesn't squash it. sips can pad but only to an opaque
# hex color (no alpha), so prefer the venv's Pillow when it exists; fall back
# to a plain resample (distorted, but the icon still renders) otherwise.
if [ -f "$LOGO" ]; then
    WORK=$(mktemp -d)
    SQUARE="$WORK/square.png"
    if [ -x "$REPO/.venv/bin/python" ] && "$REPO/.venv/bin/python" -c "import PIL" 2>/dev/null; then
        "$REPO/.venv/bin/python" - "$LOGO" "$SQUARE" <<'PY'
import sys
from PIL import Image
src, dst = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGBA")
w, h = img.size
side = int(max(w, h) * 1.25)
canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
canvas.save(dst)
PY
    else
        cp "$LOGO" "$SQUARE"
    fi

    ICONSET="$WORK/CLOUDS.iconset"
    mkdir -p "$ICONSET"
    sips -z 16 16     "$SQUARE" --out "$ICONSET/icon_16x16.png"      >/dev/null
    sips -z 32 32     "$SQUARE" --out "$ICONSET/icon_16x16@2x.png"   >/dev/null
    sips -z 32 32     "$SQUARE" --out "$ICONSET/icon_32x32.png"      >/dev/null
    sips -z 64 64     "$SQUARE" --out "$ICONSET/icon_32x32@2x.png"   >/dev/null
    sips -z 128 128   "$SQUARE" --out "$ICONSET/icon_128x128.png"    >/dev/null
    sips -z 256 256   "$SQUARE" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
    sips -z 256 256   "$SQUARE" --out "$ICONSET/icon_256x256.png"    >/dev/null
    sips -z 512 512   "$SQUARE" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
    sips -z 512 512   "$SQUARE" --out "$ICONSET/icon_512x512.png"    >/dev/null
    sips -z 1024 1024 "$SQUARE" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/CLOUDS.icns"
    rm -rf "$WORK"
fi

touch "$APP"
printf '%s\n' "create_desktop_icon.sh: built $APP"
