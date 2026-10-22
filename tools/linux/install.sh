#!/bin/sh
# Put InventCraft on this desktop: a menu entry, its icon, and the file
# types, for this user only.  Nothing here needs root.
#
#   ./install.sh            copy InventCraft to ~/.local/share/InventCraft,
#                           where it can update itself, and add it to the menu
#   ./install.sh --here     leave it in this folder and only add it to the menu
#   ./install.sh --remove   take it off the menu, and remove the copy the
#                           first form made
#
# Running it again from a newer download replaces the copy with the newer
# one, which is also how to move from a build too old to update itself.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DATA=${XDG_DATA_HOME:-"$HOME/.local/share"}
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor"
MIME="$DATA/mime"
COPY="$DATA/InventCraft"
BIN="$HOME/.local/bin"
TYPES="application/x-inventcraft-part;application/x-inventcraft-assembly;application/x-inventcraft-drawing;application/x-inventcraft-cam;"

refresh() {
    command -v update-mime-database >/dev/null 2>&1 &&
        update-mime-database "$MIME" >/dev/null 2>&1 || true
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database "$APPS" >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 &&
        gtk-update-icon-cache -f -t "$ICONS" >/dev/null 2>&1 || true
}

remove() {
    rm -f "$APPS/inventcraft.desktop" "$MIME/packages/inventcraft.xml"
    for size in 16 24 32 48 64 128 256 512; do
        rm -f "$ICONS/${size}x${size}/apps/inventcraft.png"
    done
    if [ -L "$BIN/inventcraft" ]; then
        rm -f "$BIN/inventcraft"
    fi
    # only a folder that really is an InventCraft is ever deleted
    if [ -x "$COPY/InventCraft" ]; then
        rm -rf "$COPY"
    fi
    refresh
    echo "InventCraft is off the menu.  Your documents and settings are kept."
}

case "${1:-}" in
    --remove)
        remove
        exit 0
        ;;
    --here)
        TARGET=$HERE
        ;;
    "")
        TARGET=$COPY
        if [ "$HERE" != "$COPY" ]; then
            echo "Copying InventCraft to $COPY"
            mkdir -p "$DATA"
            rm -rf "$COPY.new"
            cp -a "$HERE" "$COPY.new"
            if [ -e "$COPY" ]; then
                if [ ! -x "$COPY/InventCraft" ]; then
                    rm -rf "$COPY.new"
                    echo "$COPY exists and is not InventCraft; leaving it alone." >&2
                    exit 1
                fi
                rm -rf "$COPY"
            fi
            mv "$COPY.new" "$COPY"
        fi
        ;;
    *)
        echo "usage: $0 [--here | --remove]" >&2
        exit 2
        ;;
esac

if [ ! -x "$TARGET/InventCraft" ]; then
    echo "There is no InventCraft program in $TARGET." >&2
    exit 1
fi

# the beaver, at each size a desktop asks for
BRAND=$(find "$TARGET" -type d -path "*datum/ui/brand" 2>/dev/null | head -n 1)
if [ -n "$BRAND" ]; then
    for size in 16 24 32 48 64 128 256 512; do
        if [ -f "$BRAND/inventcraft-$size.png" ]; then
            mkdir -p "$ICONS/${size}x${size}/apps"
            cp "$BRAND/inventcraft-$size.png" \
                "$ICONS/${size}x${size}/apps/inventcraft.png"
        fi
    done
fi

# the file types, the new endings and DATUM's old ones both
mkdir -p "$MIME/packages"
cat > "$MIME/packages/inventcraft.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-inventcraft-part">
    <comment>InventCraft part</comment>
    <icon name="inventcraft"/>
    <glob pattern="*.icpart"/>
    <glob pattern="*.pdat"/>
  </mime-type>
  <mime-type type="application/x-inventcraft-assembly">
    <comment>InventCraft assembly</comment>
    <icon name="inventcraft"/>
    <glob pattern="*.icasm"/>
    <glob pattern="*.adat"/>
  </mime-type>
  <mime-type type="application/x-inventcraft-drawing">
    <comment>InventCraft drawing</comment>
    <icon name="inventcraft"/>
    <glob pattern="*.icdraw"/>
    <glob pattern="*.ddat"/>
  </mime-type>
  <mime-type type="application/x-inventcraft-cam">
    <comment>InventCraft CAM sheet</comment>
    <icon name="inventcraft"/>
    <glob pattern="*.iccam"/>
    <glob pattern="*.cdat"/>
  </mime-type>
</mime-info>
XML

# The menu entry.  StartupWMClass is DATUM because the window still
# carries the program's old name as its class, the name its settings are
# kept under, and the desktop matches the window to this entry by it.
mkdir -p "$APPS"
cat > "$APPS/inventcraft.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=InventCraft
GenericName=Parametric CAD
Comment=Parts, assemblies, drawings and CAM sheets
Exec="$TARGET/InventCraft" %f
Icon=inventcraft
Terminal=false
Categories=Graphics;Engineering;3DGraphics;
MimeType=$TYPES
StartupWMClass=DATUM
DESKTOP

# and a command, for a terminal
mkdir -p "$BIN"
ln -sf "$TARGET/InventCraft" "$BIN/inventcraft"

refresh
echo "InventCraft is on the menu, and opens .icpart, .icasm, .icdraw and .iccam files."
echo "It runs from $TARGET"
