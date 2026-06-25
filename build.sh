#!/bin/bash

SRC_NAME="wk2x_keyer"

rm -rf build
rm -rf dist
rm -rf "$SRC_NAME"
rm -f "${SRC_NAME}.spec"

# stupid windows
if [ "`uname`" == "Linux" ]; then
    pyinstaller --onefile --noconsole "${SRC_NAME}.py"
else
    python -m PyInstaller --onefile --noconsole "${SRC_NAME}.py"
fi

mkdir -p "$SRC_NAME"
cp "${SRC_NAME}.desktop" "$SRC_NAME"
cp "${SRC_NAME}_icon.png" "$SRC_NAME"
cp install.sh "$SRC_NAME"
cp uninstall.sh "$SRC_NAME"
cp README.md "$SRC_NAME"
cp LICENSE "$SRC_NAME"
cp -r dist "$SRC_NAME"

tar cvfz "${SRC_NAME}.tar.gz" "$SRC_NAME"
rm -rf "$SRC_NAME"

