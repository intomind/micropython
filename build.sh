#!/bin/sh
# Build the firmware: MicroPython 1.29.0 for the Raspberry Pi Pico 2 W, with
# the pairing and bonding from MicroPython pull request 17469, LE Secure
# Connections, and this repository's board and intomind library.
#
#     ./build.sh
#
# Needs git, make, CMake, Python 3 and the Arm compiler arm-none-eabi-gcc.
# MicroPython is cloned into build/micropython unless MICROPYTHON says where.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
MP=${MICROPYTHON:-$HERE/build/micropython}
BOARD=$HERE/board/INTOMIND_PICO2_W

if [ ! -d "$MP" ]; then
    git clone --branch v1.29.0 https://github.com/micropython/micropython.git "$MP"
fi
cd "$MP"
# Only MicroPython's own v1.29.0 commit, with the two patches applied as
# changes, and the release's date as the build date, so the file carries no
# commit and no date from the machine that built it.
if [ "$(git rev-parse HEAD)" != "$(git rev-parse 'v1.29.0^{commit}')" ]; then
    echo "$MP is not at MicroPython's v1.29.0 commit." >&2
    exit 1
fi
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct v1.29.0)
# The version names what this build adds to MicroPython 1.29.0.
MICROPY_GIT_TAG=v1.29.0-intomind
export SOURCE_DATE_EPOCH MICROPY_GIT_TAG
# The two patches, once.
if ! grep -q btstack_tlv_mp extmod/btstack/modbluetooth_btstack.c; then
    git apply "$HERE/patches/0001-extmod-btstack-implement-pairing-and-bonding.patch"
fi
if ! grep -q ENABLE_LE_SECURE_CONNECTIONS ports/rp2/btstack_inc/btstack_config.h; then
    git apply "$HERE/patches/0002-rp2-le-secure-connections.patch"
fi
make -C mpy-cross
make -C ports/rp2 BOARD_DIR="$BOARD" submodules
make -C ports/rp2 BOARD_DIR="$BOARD" -j"$(nproc 2>/dev/null || echo 4)"
cp ports/rp2/build-INTOMIND_PICO2_W/firmware.uf2 "$HERE/firmware/intomind-micropython-pico-2-w.uf2"
cd "$HERE/firmware"
sha256sum intomind-micropython-pico-2-w.uf2 > SHA256SUMS
cat SHA256SUMS
