# Bench network + Pi deployment (PC ↔ Pi)

Moved out of `CLAUDE.md` 2026-09-18.

Direct Ethernet, no switch, no DHCP, no gateway — host-to-host only, so both
machines keep their normal default route (the Pi's internet is `wlan0`).

| End | Address | Ports |
|---|---|---|
| PC (ground) | `192.168.100.1/24` static | — |
| Pi (experiment) | `192.168.100.10/24` static, `eth0` | UDP 4000 downlink, TCP 4001 commands, TCP 4010 bench frames |

Addresses match `FswConfig.ground_host` and the GSE `--experiment` default, so
both run with no host flags. `pi.local` resolves to the **WiFi** address —
address `192.168.100.10` explicitly for the cable, and check `$SSH_CONNECTION`.
Pi config is persistent in `/etc/netplan/90-NM-75a1216a-*.yaml`.

**The bench Pi is a Raspberry Pi 4 Model B Rev 1.2**, not the Pi 5 the SED
and every README baseline (`cat /proc/device-tree/model`). It matters for the
UART: the Pi 5 route is `dtparam=uart0=on` / the `uart0-pi5` overlay, while
what this board needed was the Pi-4 route below. Same disagreement class as
the IMU - hardware and document differ, and the document is the one that has
not been updated.

**Enabling the RP2350 UART on the bench Pi** took three changes and two
reboots, and the intermediate state looks like success:

```sh
# /boot/firmware/config.txt
enable_uart=1
dtoverlay=disable-bt        # without this serial0 -> ttyS0, the mini-UART
# /boot/firmware/cmdline.txt: drop console=serial0,115200
```

`enable_uart=1` alone gives `/dev/serial0 -> ttyS0`: the **mini-UART**, whose
baud follows the core clock, with Bluetooth holding the PL011 as `ttyAMA1`.
There is no `/dev/ttyAMA0` at all in that state, so `uart_port` in
`/etc/clouds/fsw.json` fails and the service crash-loops. `disable-bt` frees
the PL011 and `serial0 -> ttyAMA0` appears. Then delete the `--no-uart` in
`/etc/systemd/system/clouds-fsw.service.d/10-bench.conf`, which exists only
for a Pi with no MCU wired.

Pi is **Debian 13 / Python 3.13, PEP 668** — install deps with apt
(`python3-numpy python3-scipy python3-serial`), not pip; pip would build scipy
from source on ARM. Deployment lives in `/opt/clouds` with `clouds_fsw/`,
`clouds_link/`, `spectro/` side by side and **`calibration.json` as a sibling of
`spectro/`** (`_DEFAULT_JSON` resolves to `spectro/../calibration.json`).
Vendor library: `/usr/local/lib/libe9u_LSMD.so` via
`drivers/e9u_LSMD_LIB_Linux/install.sh`.
