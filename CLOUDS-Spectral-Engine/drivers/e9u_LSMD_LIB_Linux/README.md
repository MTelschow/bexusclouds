# EURECA e9u_LSMD camera library — Linux (vendor source, v2.4.02)

The Linux half of the Duo vendor library: same `e9u_LSMD_*` API as the Windows
`vendor/libe9u_LSMD_x64.dll`, built from source into `libe9u_LSMD.so`. This is
what closes **feature P-01** — `spectro/eureca_driver.py` now loads either one,
so the Raspberry Pi flight software (`flight/pi/`) can drive the real
spectrometer instead of only `--mock`.

| Path | What |
|---|---|
| `e9u_lsmd_camera_library_Linux-2.4.02.tar.gz` | vendor release, unmodified (autotools source, LGPL-3.0) |
| `install.sh` | extract → `./configure --disable-gui` → `make` → `make install` → udev |
| `include/` | the public headers, unpacked for reading (the ctypes wrapper mirrors these) |
| `udev/51-eureca-e9u-lsmd.rules` | the vendor udev rules, unpacked for review |

The tarball is the authoritative artefact — `install.sh` builds *from it*, not
from the unpacked copies here. Those exist so the API contract is reviewable in
git without unpacking anything.

## Build & install on the Pi

```sh
sudo apt-get install build-essential          # gtk is NOT needed, see below
drivers/e9u_LSMD_LIB_Linux/install.sh
```

`install.sh` passes `--disable-gui`, so the build needs no GTK and produces no
vendor GUI — the Engine and the FSW are the only consumers. It installs to
`/usr/local` (override with `--prefix`), runs `ldconfig`, and installs the udev
rules (skip with `--no-udev`). Privileged steps are echoed before they run and
use `$SUDO` (`SUDO= install.sh` to run them unprivileged, e.g. as root).

Then check the library is loadable and the camera is found:

```sh
python -c "import spectro.eureca_driver as d; print(d._load_vendor_lib())"
python -c "from spectro.driver import open_driver; print(open_driver().connect().summary())"
```

## Why udev matters

The board is an FTDI FT2232H (VID `0403` / PID `6010`) with **two** interfaces.
The rules do two things:

1. `MODE="0666"` on EURECA tty devices, so the library can open `/dev/ttyUSB*`
   without root.
2. Unbind `ftdi_sio` from **interface 0** for known board types, so only the
   data interface enumerates as a tty.

Point 2 is keyed on the interface string, and the shipped rules list
`e9u_LSMD-TCD1304-{ECO,STD,TRG,PRO}` — **not** `-PCB`, which the library's own
board table also knows (`lib/src/e9u_LSMD_interface.c`). If the flight unit
reports a type that is not listed, add a matching line. Without it the device
still works — `e9u_LSMD_search_for_camera` walks `/dev/ttyUSB99` down to `0` and
handshakes each one — it just probes a spare tty first.

Confirm the board type after connecting:

```sh
udevadm info -a -n /dev/ttyUSB0 | grep -i 'interface\|manufacturer'
```

## API surface

`include/e9u_LSMD_macros.h` holds the convenience calls the driver binds
(`search_for_camera`, `start_camera_async`, `set_times_us`, `get_next_frame`);
`include/e9u_LSMD.h` the lower-level ones (`get_pixel_pointer`,
`get_dark_value`, `get_frame_counter`, …). Signatures are identical on both
platforms — the same `lib/src/*.c` builds the DLL and the `.so`, with
`e9u_LSMD_Linux.c` / `e9u_LSMD_Windows.c` as the only backend difference. The
one platform-visible consequence: the device prefix is `/dev/ttyUSB` on Linux
and `\\.\COM` on Windows (`e9u_LSMD_Linux.h` / `e9u_LSMD_Windows.h`), so the
identity line the driver parses reads `using device /dev/ttyUSB0:`.

The library also offers a shared-memory / socket server (`e9u_LSMD_begin_shm`,
`e9u_LSMD_mmap_server`) to decouple acquisition from the application. We do not
use it: the FSW's `SpectroSource` already owns a dedicated acquisition thread,
and one fewer process is one fewer thing to supervise in flight.

## Licence

LGPL-3.0 (`COPYING`, `COPYING.LESSER` inside the tarball; the same texts sit in
`vendor/` for the Windows build). Vendored unmodified — patch via the build, not
by editing the tarball, so the provenance stays checkable.

## Not covered: the EDU board

This is the **Duo/STD** family only. The single-channel EDU board
(`drivers/e9u_LSMD_EDU_LIB/`, exports `e9u_LSMD_EDU_*`) ships a Windows backend
and DLL but no Linux source, so `spectro/eureca_edu_driver.py` is Windows-only
and raises a clear `DriverError` elsewhere. The Pi flies the Duo.
