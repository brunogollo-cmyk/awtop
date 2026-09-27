#!/bin/sh
#
# install.sh - install or remove awtop system-wide
#
# Usage:
#   sudo ./install.sh              install
#   sudo ./install.sh --uninstall  remove
#   PREFIX=~/.local sudo -E ./install.sh   install under a different prefix
#
set -e

PREFIX="${PREFIX:-/usr/local}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$PREFIX/lib/awtop"
BIN="$PREFIX/bin/awtop"

usage() {
    sed -n '/^# Usage:/,/^#$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

case "${1:-}" in
    -h|--help) usage ;;
esac

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo $0" >&2
    exit 1
fi

# --- uninstall ------------------------------------------------------------

if [ "${1:-}" = "--uninstall" ]; then
    echo "Removing $BIN and $LIB_DIR..."
    rm -f "$BIN"
    rm -rf "$LIB_DIR"
    echo "Done."
    exit 0
fi

# --- dependency check -----------------------------------------------------

check_deps() {
    missing=""
    python3 -c "import psutil" 2>/dev/null || missing="$missing python3-psutil"
    python3 -c "import rich" 2>/dev/null || missing="$missing python3-rich"
    if [ -n "$missing" ]; then
        echo "Missing dependencies:$missing" >&2
        echo "Install them with: sudo apt install$missing" >&2
        exit 1
    fi
}

check_deps

# --- install --------------------------------------------------------------

echo "Installing package to $LIB_DIR..."
mkdir -p "$LIB_DIR"
rm -rf "$LIB_DIR/awtop"
cp -r "$SRC_DIR/awtop" "$LIB_DIR/awtop"
find "$LIB_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

echo "Installing launcher to $BIN..."
mkdir -p "$PREFIX/bin"
cat > "$BIN" <<LAUNCHER
#!/usr/bin/env python3
import sys

sys.path.insert(0, "$LIB_DIR")

from awtop.app import main

if __name__ == "__main__":
    main()
LAUNCHER
chmod 0755 "$BIN"

echo "Done. Run: sudo awtop"
