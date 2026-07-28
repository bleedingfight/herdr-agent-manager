#!/usr/bin/env bash
set -euo pipefail

# One-click installer for herdr-agent-manager.
# Run from inside this plugin directory:
#   ./install.sh

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
HERDR_DIR="${HOME}/.config/herdr"
TARGET_DIR="${HERDR_DIR}/plugins/local/agent-manager"
CONFIG="${HERDR_DIR}/config.toml"

if ! command -v herdr >/dev/null 2>&1; then
    echo "Error: herdr is not installed or not in PATH."
    exit 1
fi

mkdir -p "$(dirname "$TARGET_DIR")"

if [ -d "$TARGET_DIR" ] && [ "$PLUGIN_DIR" != "$TARGET_DIR" ]; then
    backup="${TARGET_DIR}.backup.$(date +%s)"
    echo "Existing plugin found, backing up to: $backup"
    mv "$TARGET_DIR" "$backup"
fi

if [ "$PLUGIN_DIR" != "$TARGET_DIR" ]; then
    echo "Installing plugin to $TARGET_DIR"
    cp -R "$PLUGIN_DIR" "$TARGET_DIR"
fi

cd "$TARGET_DIR"
chmod +x bin/*.py

echo "Linking plugin in herdr"
herdr plugin link "$TARGET_DIR" || true

if [ ! -f "$CONFIG" ]; then
    echo "Warning: herdr config not found at $CONFIG"
    echo "Please add the keybindings from README.md manually."
    exit 0
fi

if grep -q 'local/agent-manager/bin/agent-manager.py' "$CONFIG"; then
    echo "Keybindings already present in $CONFIG"
else
    echo "Adding keybindings to $CONFIG"
    cat >> "$CONFIG" <<EOF

# Agent Manager plugin keybindings
[[keys.command]]
key = "prefix+a"
type = "pane"
command = "$TARGET_DIR/bin/agent-manager.py"

[[keys.command]]
key = "prefix+w"
type = "pane"
command = "$TARGET_DIR/bin/space-picker.py"
EOF
fi

echo "Reloading herdr config"
herdr server reload-config

echo "Done. Try: ctrl+b a  or  ctrl+b w"
