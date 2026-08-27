#!/usr/bin/env bash
set -euo pipefail

# One-click installer for herdr-agent-manager — fish-style automated install.
#
#   curl -fsSL https://raw.githubusercontent.com/bleedingfight/herdr-agent-manager/main/install.sh | bash
#
# Or download first:
#   curl -fsSL -o install.sh https://raw.githubusercontent.com/bleedingfight/herdr-agent-manager/main/install.sh
#   bash install.sh
#
# What it does: checks every dependency and tells you exactly how to install
# anything missing, clones the plugin (if run standalone), links it into herdr,
# and writes idempotent keybindings. Re-running is safe.
#
# Idempotence: before appending keybindings, the script removes every stale
# [[keys.command]] block that points at this plugin's scripts — including the
# old github-hash path form (local.agent-manager-<hash>/bin/...) left behind by
# `herdr plugin install`. So mixing install methods never leaves duplicate or
# dead bindings; the final config always has exactly one fresh set.

REPO_URL="https://github.com/bleedingfight/herdr-agent-manager.git"

HERDR_DIR="${HOME}/.config/herdr"
TARGET_DIR="${HERDR_DIR}/plugins/local/agent-manager"
CONFIG="${HERDR_DIR}/config.toml"

# --- pretty output (auto-disables color when not a TTY, e.g. curl|bash) -------
if [ -t 1 ]; then
    C_TAG=$'\033[1;34m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else
    C_TAG=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi
log()  { printf '%s[agent-manager]%s %s\n'        "$C_TAG" "$C_OFF" "$*" >&2; }
ok()   { printf '%s[agent-manager]%s %s✓%s %s\n'  "$C_TAG" "$C_OFF" "$C_OK"  "$C_OFF" "$*" >&2; }
warn() { printf '%s[agent-manager]%s %s!%s %s\n'  "$C_TAG" "$C_OFF" "$C_WARN" "$C_OFF" "$*" >&2; }
die()  { printf '%s[agent-manager]%s %s✗%s %s\n'  "$C_TAG" "$C_OFF" "$C_ERR"  "$C_OFF" "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# Print a best-effuffort install command for a missing tool, adapted to the
# current platform / package manager.
install_hint() {
    case "$1" in
        git)
            if have brew; then         echo "brew install git"
            elif have apt-get; then    echo "sudo apt-get install -y git"
            elif have dnf; then        echo "sudo dnf install -y git"
            else                       echo "see https://git-scm.com/downloads"
            fi ;;
        fzf)
            if have brew; then         echo "brew install fzf"
            elif have apt-get; then    echo "sudo apt-get install -y fzf"
            elif have dnf; then        echo "sudo dnf install -y fzf"
            elif have pacman; then     echo "sudo pacman -S --noconfirm fzf"
            else                       echo "see https://github.com/junegunn/fzf#installation"
            fi ;;
        python3)
            if have brew; then         echo "brew install python"
            elif have apt-get; then    echo "sudo apt-get install -y python3"
            elif have dnf; then        echo "sudo dnf install -y python3"
            else                       echo "see https://www.python.org/downloads/"
            fi ;;
        herdr)
            echo "see https://herdr.dev  (Herdr >= 0.7.0 required)" ;;
    esac
}

# Require a tool, or die with a tailored install hint. $1=tool $2=why.
require() {
    if have "$1"; then ok "$1 found ($(command -v "$1"))"; return 0; fi
    die "$1 is required ($2). Install it first:  $(install_hint "$1")"
}

log "Detected OS: $(uname -s) $(uname -m)"

# --- dependencies required by every install path -----------------------------
require herdr   "hosts the plugin"
require fzf     "picker UI"
require python3 "picker scripts"

# --- decide mode: standalone (curl|bash) vs in-repo --------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Standalone mode: this script isn't sitting inside a full plugin dir (e.g.
# piped from curl). Clone the repo to a temp dir and hand off to the real
# install.sh inside the clone.
if [ ! -f "$SCRIPT_DIR/herdr-plugin.toml" ] || [ ! -d "$SCRIPT_DIR/bin" ]; then
    require git "one-click clone"
    log "One-click mode: cloning $REPO_URL"
    TMP="$(mktemp -d)"
    set +e
    git clone --depth 1 "$REPO_URL" "$TMP/repo" >&2
    rc=$?
    set -e
    if [ $rc -ne 0 ]; then
        rm -rf "$TMP"
        die "git clone failed (rc=$rc). Check the URL / your network and retry."
    fi
    bash "$TMP/repo/install.sh" "$@"
    rc=$?
    rm -rf "$TMP"
    exit $rc
fi

# --- in-repo mode: SCRIPT_DIR is a full plugin directory ---------------------
PLUGIN_DIR="$SCRIPT_DIR"
log "Installing from $PLUGIN_DIR"

mkdir -p "$(dirname "$TARGET_DIR")"

if [ -d "$TARGET_DIR" ] && [ "$PLUGIN_DIR" != "$TARGET_DIR" ]; then
    backup="${TARGET_DIR}.backup.$(date +%s)"
    warn "existing install found, backing up to: $backup"
    mv "$TARGET_DIR" "$backup"
fi

if [ "$PLUGIN_DIR" != "$TARGET_DIR" ]; then
    log "Copying plugin to $TARGET_DIR"
    cp -R "$PLUGIN_DIR" "$TARGET_DIR"
fi

cd "$TARGET_DIR"
chmod +x bin/*.py

log "Linking plugin in herdr"
herdr plugin link "$TARGET_DIR" >/dev/null || true
ok "plugin linked (id: local.agent-manager)"

# --- keybindings: strip every stale block, then append one fresh set --------
if [ ! -f "$CONFIG" ]; then
    warn "herdr config not found at $CONFIG"
    warn "add the keybindings from README.md manually, then: herdr server reload-config"
    exit 0
fi

log "Cleaning stale keybindings in $CONFIG (if any)"
python3 - "$CONFIG" <<'PYEOF'
import sys
path = sys.argv[1]
try:
    with open(path) as f:
        lines = f.readlines()
except FileNotFoundError:
    sys.exit(0)

MARKERS = ("agent-manager.py", "space-picker.py")
out = []
i = 0
n = len(lines)
while i < n:
    if lines[i].strip() == "[[keys.command]]":
        # Collect the block: header + lines until the next table header.
        j = i + 1
        block = [lines[i]]
        while j < n:
            s = lines[j].strip()
            if s.startswith("[[") or (s.startswith("[") and not s.startswith("[[")):
                break
            block.append(lines[j])
            j += 1
        block_text = "".join(block)
        if any(m in block_text for m in MARKERS):
            # This block points at our scripts — drop it. Also eat any
            # immediately preceding comment/blank lines that belong to us
            # (only if that comment run mentions Agent Manager / agent-manager,
            # so an unrelated user comment is never touched).
            k = len(out)
            while k > 0:
                s = out[k - 1].strip()
                if s == "" or s.startswith("#"):
                    k -= 1
                else:
                    break
            seg = out[k:]
            if any(("Agent Manager" in x) or ("agent-manager" in x) for x in seg):
                del out[k:]
            i = j
            continue
        out.extend(block)
        i = j
        continue
    out.append(lines[i])
    i += 1

with open(path, "w") as f:
    f.writelines(out)
PYEOF

log "Appending fresh keybindings to $CONFIG"
cat >> "$CONFIG" <<EOF

# Agent Manager plugin keybindings
# type = "pane" (NOT "plugin_action"): these pickers run raw fzf, which needs
# an interactive TTY; type="plugin_action" spawns without one and fzf hangs.
[[keys.command]]
key = "prefix+a"
type = "pane"
command = "$TARGET_DIR/bin/agent-manager.py"
description = "Pick agent and send message"

[[keys.command]]
key = "prefix+w"
type = "pane"
command = "$TARGET_DIR/bin/space-picker.py"
description = "Pick workspace/space"
EOF
ok "keybindings written (prefix+a, prefix+w)"

log "Reloading herdr config"
if herdr server reload-config >/dev/null 2>&1; then
    ok "config reloaded"
else
    warn "could not reload config (old server protocol?). Run: herdr server stop && herdr"
fi

cat >&2 <<EOF

${C_TAG}[agent-manager]${C_OFF} ${C_OK}Done.${C_OFF}
  ctrl+b a   agent picker
  ctrl+b w   workspace/space picker

  Update:  re-run this script (or: herdr plugin install bleedingfight/herdr-agent-manager --yes)
  Remove:  herdr plugin unlink local.agent-manager  &&  rm -rf ${TARGET_DIR}
EOF
