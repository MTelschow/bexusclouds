#!/bin/sh
# Build + install the EURECA e9u_LSMD Linux camera library (feature P-01).
#
#   install.sh [--prefix DIR] [--build-dir DIR] [--no-udev] [--no-install]
#
# Headless by design: --disable-gui, so no GTK dependency and no vendor GUI.
# Privileged steps are echoed before they run and go through $SUDO
# (SUDO= install.sh to run them directly, e.g. already root).
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
TARBALL="$HERE/e9u_lsmd_camera_library_Linux-2.4.02.tar.gz"
SRCDIR_NAME="e9u_lsmd_camera_library-2.4.02"

PREFIX=/usr/local
BUILD_DIR=""
DO_UDEV=1
DO_INSTALL=1
SUDO=${SUDO-sudo}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix)     PREFIX=${2:?--prefix needs a directory}; shift 2 ;;
        --build-dir)  BUILD_DIR=${2:?--build-dir needs a directory}; shift 2 ;;
        --no-udev)    DO_UDEV=0; shift ;;
        --no-install) DO_INSTALL=0; shift ;;
        -h|--help)    sed -n '2,8p' "$0"; exit 0 ;;
        *)            echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

[ -f "$TARBALL" ] || { echo "missing vendor tarball: $TARBALL" >&2; exit 1; }
[ -n "$BUILD_DIR" ] || BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/e9u_lsmd_build.XXXXXX")
mkdir -p "$BUILD_DIR"

run_priv() {
    echo "+ ${SUDO:+$SUDO }$*"
    ${SUDO:+$SUDO} "$@"
}

echo "== unpacking $(basename "$TARBALL") -> $BUILD_DIR"
tar -xzf "$TARBALL" -C "$BUILD_DIR"
SRC="$BUILD_DIR/$SRCDIR_NAME"
[ -d "$SRC" ] || { echo "unexpected tarball layout: no $SRCDIR_NAME/" >&2; exit 1; }

echo "== configure (headless, prefix=$PREFIX)"
( cd "$SRC" && ./configure --prefix="$PREFIX" --disable-gui )

echo "== build"
( cd "$SRC" && make -j "$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)" )

if [ "$DO_INSTALL" -eq 1 ]; then
    echo "== install libe9u_LSMD.so + headers"
    ( cd "$SRC" && run_priv make install )
    run_priv ldconfig
fi

if [ "$DO_UDEV" -eq 1 ]; then
    echo "== udev rules (0666 on EURECA ttys + unbind ftdi_sio from interface 0)"
    run_priv install -m 0644 \
        "$SRC/etc/udev/rules.d/51-eureca-e9u-lsmd.rules" /etc/udev/rules.d/
    run_priv udevadm control --reload-rules
    # The vendor rules are all ACTION=="add", but `udevadm trigger` defaults to
    # "change": a plain trigger reloads them and applies nothing, leaving the
    # tty at 0660 with ftdi_sio still bound to interface 0 while *looking* like
    # it worked. Replay real add events for the buses that matter instead.
    run_priv udevadm trigger --action=add --subsystem-match=usb \
        --subsystem-match=tty
    run_priv udevadm settle
fi

cat <<EOF

== done. Library: $PREFIX/lib/libe9u_LSMD.so
   If $PREFIX/lib is not on the loader path, either add it to /etc/ld.so.conf
   (then 'sudo ldconfig') or point the driver at it:
       export CLOUDS_E9U_LIB_DIR=$PREFIX/lib
   Check it comes up (the udev step above already replayed the add events;
   a physical replug, or a software one, also works):
       python -c "from spectro.driver import open_driver; print(open_driver().connect().summary())"
   Expect ".. 2048px" and one tty at 0666 with interface :1.0 unbound:
       ls -l /dev/ttyUSB*; ls /sys/bus/usb/devices/<dev>:1.0/driver
   Software replug if a rule lands after the device (<dev> e.g. 1-1.2):
       echo -n <dev> | sudo tee /sys/bus/usb/drivers/usb/unbind
       echo -n <dev> | sudo tee /sys/bus/usb/drivers/usb/bind
   Build tree left at: $SRC
EOF
