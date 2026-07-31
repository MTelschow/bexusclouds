# Driver layer

`spectro/driver.py` defines `SpectrometerDriver`, the hardware-agnostic
interface the UI talks to. Implementations:

* `eureca_driver.py` - the real EURECA Duo, Windows **and** Linux
  (default, `kind="std"`).
* `eureca_edu_driver.py` - the real EURECA e9u_LSMD_EDU single-channel board
  (`kind="edu"`, `python clouds_spectral.py --edu`). Windows only. See below.
* `mock_driver.py` - synthetic Duo frames, so `verify.py` and `verify_qt.py`
  run with no hardware.

The UI never imports a concrete driver directly; it asks `open_driver(mock=...,
kind=...)` for "real or mock" and, for real hardware, "std or edu" (also
settable via the `CLOUDS_SPECTRO_KIND` env var, and by `spectro_kind` in the
FSW-PI config) - so future Ground Support Equipment (GSE) / downlink consumers
can reuse the same interface (a downlink source in place of the USB driver).

## EURECA Duo vendor library (`libe9u_LSMD_x64.dll` / `libe9u_LSMD.so`)

One driver, two platforms - the *same* vendor sources build both, so only
library loading differs. Signatures below are from the vendor headers
(`drivers/e9u_LSMD_LIB_Linux/include/`), which are the authority for both.

| | Windows | Linux |
|---|---|---|
| Library | `libe9u_LSMD_x64.dll` (prebuilt, in `vendor/`) | `libe9u_LSMD.so` (built from source, `drivers/e9u_LSMD_LIB_Linux/`) |
| ctypes loader | `WinDLL` + `os.add_dll_directory` (mingw runtime deps sit beside the DLL) | `CDLL` |
| Search order | `CLOUDS_E9U_DLL_DIR` -> `vendor/` -> the known `EURECA_e9u\e9u_LSMD_GTK_x64` folder | `CLOUDS_E9U_LIB_DIR` -> `vendor/` -> `/usr/local/lib`, `/usr/lib` -> the dynamic loader (`ldconfig`) |
| Device scan | `\\.\COM99` down to `COM0` | `/dev/ttyUSB99` down to `ttyUSB0` |
| Access control | FTDI VCP driver, auto-installs | **udev rules required** (0666 + unbind `ftdi_sio` from interface 0) |

Functions used (camera index 0, channel 0):

| Function | Signature | Purpose |
|---|---|---|
| `e9u_LSMD_search_for_camera(uint)` -> int | 0 = found | auto-detect on any port |
| `e9u_LSMD_start_camera_async(uint)` -> int | | start async acquisition |
| `e9u_LSMD_set_times_us(uint,uint,uint)` -> int | (cam, exposure_us, frame_us) | integration + frame time |
| `e9u_LSMD_get_next_frame(uint)` -> int | | wait for / fetch the next frame |
| `e9u_LSMD_get_pixel_pointer(uint,uint)` -> uint16* | (cam, channel) | pointer to the 2048-px buffer |
| `e9u_LSMD_get_dark_value(uint,uint,uint,uint)` -> int | (cam, channel, x, y) | on-chip black level (optional) |
| `e9u_LSMD_get_frame_counter(uint,uint)` -> uint | (cam, channel) | drop/duplicate detection (optional) |

A frame is 2048 x uint16 read from the pixel pointer after each
`get_next_frame`. After changing the integration time, discard a couple of
frames so the new timing settles before trusting the data.

The whole Duo is **one camera** to the library: one readout produces both fibre
channels in one 2048-px frame, at one shared integration time. Hence channel 0
everywhere - the two *fibre* channels are a calibration-level pixel split, not
library channels.

> The last two rows are read-only extras the UI shows opportunistically. Both
> take **more than the camera index** - a one-argument binding (as this driver
> had before the headers were vendored) passes whatever happens to be in the
> argument registers as `channel`/`x`/`y` and returns junk. They stay wrapped in
> `try/except` returning `None`, so a vendor build without them degrades
> silently.

### Identity string

`search_for_camera` reports the camera by `printf`, so the driver captures fd 1
around the call and parses `model` / `SN` / `FW` / `Pixel:` out of it. On Linux
glibc block-buffers when fd 1 is a file, so the driver also calls
`fflush(NULL)` on the process libc (shared with the `.so`) before reading. This
is best-effort: losing the text costs only the identity fields, never the
connect result, which comes from the return code.

### Linux setup

Build and install with `drivers/e9u_LSMD_LIB_Linux/install.sh` (headless:
`./configure --disable-gui`, no GTK needed). It also installs the vendor udev
rules, which matter more than on Windows: the FT2232H exposes two interfaces,
and the rules both open up permissions (`MODE="0666"` on EURECA ttys) and
unbind `ftdi_sio` from interface 0. The shipped rules cover board types
`e9u_LSMD-TCD1304-{ECO,STD,TRG,PRO}` but not `-PCB`; an unlisted type still
works (the scan handshakes every tty) but probes a spare device first. Details
and checks in that folder's README.

## EURECA vendor DLL (`libe9u_LSMD_EDU_x64.dll`)

A different device family, vendored under `drivers/e9u_LSMD_EDU_LIB/` (headers,
C source, x64 lib - the vendor's own GTK reference GUI is not vendored, it's
unused by this Engine). One **e9u_LSMD-TCD1304-EDU** board,
one fibre, **3648 px**, no reference channel - matches `calibration_edu.json`,
which `--edu` loads by default (`calibration.json` would slice a phantom
reference channel out of a single-fibre frame).
It talks over an FTDI VCP UART (not the Duo's async USB link) and exports its
own `e9u_LSMD_EDU_*` symbols - no relation to the Duo's `e9u_LSMD_*` exports,
so it needed its own driver (`eureca_edu_driver.py`) rather than a DLL swap.

| Function | Signature | Purpose |
|---|---|---|
| `e9u_LSMD_EDU_search_for_camera(uint,int)` -> int | (cam, i_USB=1) | scan COM0-COM99 for the board, identify + open it |
| `e9u_LSMD_EDU_start_camera_async(uint)` -> int | | no-op on this board (kept for API symmetry with the Duo) |
| `e9u_LSMD_EDU_set_exp_time_us(uint,uint)` -> int | (cam, exposure_us) | integration time (single value - no separate frame time) |
| `e9u_LSMD_EDU_get_next_frame(uint)` -> int | | trigger + read the next frame over UART |
| `e9u_LSMD_EDU_get_pixel_pointer(uint)` -> uint16* | (cam) | pointer to the pixel buffer (one arg - single channel) |
| `e9u_LSMD_EDU_get_pixel_count(uint)` -> int | | pixel count (3648) |

The DLL exposes no public close/disconnect call for this camera index (the
`e9u_LSMD_EDU_IO_*` teardown functions take a `struct e9u_LSMD_EDU*` we don't
have from the outside) - `close()` just drops the ctypes handle; the OS
reclaims the COM port on process exit. Select it with `kind="edu"` /
`CLOUDS_SPECTRO_KIND=edu` / `python clouds_spectral.py --edu`; the DLL
directory resolves as `CLOUDS_E9U_EDU_DLL_DIR` env -> repo-local
`drivers/e9u_LSMD_EDU_LIB/lib_x64/` -> `vendor/`.

**Windows only.** The vendored EDU SDK has a Windows backend
(`lib_src/e9u_LSMD_EDU_Windows.c`) and the x64 DLL, but no Linux backend
source - unlike the Duo family. So `kind="edu"` raises a `DriverError` naming
the alternative off Windows, and the Pi flies the Duo (feature P-01).

## Detector

The sensor is a **Toshiba TCD1304DG** linear CCD (confirmed from the DLL identity
line `DT: TCD1304DG`; 8 µm pitch, read out as 2048 active px here), behind an
**INSION** optical bench, on a EURECA FPGA/USB board. Firmware prints `CG1.36`
(≈ conversion gain, e-/count) and `RN46.1` (≈ read noise, e-); measured read noise
is ~20 counts (≈46-50 e-). Full well / gain are ~2x uncertain (≈40-89 ke- /
0.6-1.4 e-/count). Absolute optical-power sensitivity is in `docs/BENCH.md`.

## Gotchas

**Charge-only cable → no enumeration.** A *charge-only* USB cable makes the camera
fail USB enumeration entirely (`Unknown USB Device (Port Reset Failed)` / Code 43,
VID_0000) - invisible to the DLL. Use a real **data** cable. The FTDI VCP driver is
already staged in Windows' DriverStore and auto-installs on enumeration; it is
never the blocker.

**Frame corruption on a long cable.** Over a long USB run (the bench unit is on
**~5 m**, at the USB-2.0 passive limit, kept long for remote work), the transfer
corrupts a *random* ~9 % of pixels **each frame** to a fixed ~33514 (16-bit) code.
The corrupted set **moves** frame-to-frame, so it is NOT a fixed hot-pixel pattern
and dark-subtraction will not remove it. It is a data-path artifact, not the
detector — the other ~91 % of pixels carry the true signal at a normal ~20-count
read noise. Mitigations:
1. **Software:** combine a frame stack by **per-pixel median**, or clip samples in
   the ~33514 band, before averaging. Never plain-`mean()` a stack — the ~9 %
   spikes lift a true ~1500-count baseline to ~4500. (`processing.average_frames`
   should grow a median/clip mode for hardware data; `analyze_power.py` already
   clips the code.)
2. **Hardware:** a short, shielded (or active/repeater) USB cable removes it at the
   source. EURECA explicitly recommends short, shielded cables.

**Does the filter ever remove real signal? No -- by construction and by measurement.**
The despike removes only an ISOLATED 1-px spike that exceeds its *higher* neighbour by
>=3x; a real spectral line is >=3.7 px wide (7.4 nm FWHM / 1.99 nm/px) and always has a
high neighbour toward its centre, so it is never flagged. Injecting synthetic lines into
real frames: lines >=1.75 px are preserved to 100%, the 3.7 px instrument line to 100%
(>2x margin); only sub-1.5 px features (which the optics cannot produce) are touched.
Downward features (absorption dips, transmission/absorbance) are never flagged. The
temporal median is inherently lossless for real signal (it is present in every frame).
A UI toggle (**glitch filter**) and `processing.average_frames(..., clean=False)` expose
the unfiltered raw stream at any time, the CSV/PDF export records `glitch_filtered`, and
the preservation property is locked by a regression test in `verify.py`. Confirm the real
line-spread width against a sharp source (a laser line or the EURECA red CCFL) during
calibration.

## Device API surface & safety

`inspect_dll.py` enumerates the vendor DLL's 124 exported symbols. Two takeaways:

**There is NO firmware-write path.** No `flash` / `erase` / `program` / `bootloader`
/ `bitstream` / EEPROM-write export exists anywhere in `libe9u_LSMD_x64.dll` (raw
scan: zero hits). The FPGA board can only be reflashed by a separate vendor tool
with the board in bootloader mode + a bitstream file -- never by this runtime DLL.
So **the Engine cannot delete or overwrite the spectrometer firmware**, by
construction. The only "write" exports are runtime config: `overwrite_reg*` /
`set_reg` / `update_regs` (FPGA registers, e.g. exposure/gain -- reset on
power-cycle), `set_dark_value` / `set_pixel_value` (host-side buffers), and
`UART_write` / `I2C_transfer` (command/peripheral bus). Our driver binds ONLY
read/acquire functions (`search_for_camera`, `start_camera_async`, `set_times_us`,
`get_next_frame`, `get_pixel_pointer`, plus the optional `get_dark_value` /
`get_frame_counter` reads), so it cannot call any write function even by
accident -- keep that allowlist tight. The Linux `.so` is built from the same
vendor sources, so the property is not Windows-specific; the source tree in
`drivers/e9u_LSMD_LIB_Linux/` makes it directly auditable rather than inferred
from an export scan.

**Useful reads we don't use yet** (all read-only): `minimum_exposure` /
`minimum_frame` (true timing floor), `eeprom_string` / `eeprom_info` /
`features` / `board_info` (full device descriptor), `check_new_frames`
(non-blocking frame-ready -- a candidate fix for the read-before-ready glitch at
the source), and `start_camera_trigger` (external-trigger mode for future
hardware sync). `get_dark_value` (on-chip black-level reference) and
`get_frame_counter` (drop/duplicate detection -- pairs with the USB glitch
gauge) *are* wired up, via `SpectrometerDriver.dark_value()` /
`frame_counter()`.
