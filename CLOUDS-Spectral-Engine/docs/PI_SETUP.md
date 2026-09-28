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

**I2C on the bench Pi** was enabled 2026-09-28, to look for a BME280 on the
Pi's own header. Raspberry Pi OS ships it off, and nothing in the flight
software uses it: every flight sensor is on the MCU (`docs/HARDWARE.md`).
GPIO2/3 (header pins 3/5, SDA1/SCL1) were idle inputs with pull-ups, so it
conflicts with nothing. It needs two changes and one reboot:

```sh
# /boot/firmware/config.txt  (pre-change copy: config.txt.bak-pre-i2c)
dtparam=i2c_arm=on
# /etc/modules
i2c-dev
```

After the reboot `/dev/i2c-1` is the header bus. `/dev/i2c-20` and
`/dev/i2c-21` also appear; they belong to the HDMI/VideoCore side, not the
header. `i2c-tools` is **not installed**: `apt-get install i2c-tools` timed out.
Without it, scan from Python using `I2C_SLAVE` (`0x0703`) and a 1-byte read on
each address. On 2026-09-28 nothing answered at any address, including
0x76/0x77. The switch is persistent. To undo it, restore the backup and
drop `i2c-dev`.

Pi is **Debian 13 / Python 3.13, PEP 668** — install deps with apt
(`python3-numpy python3-scipy python3-serial`), not pip; pip would build scipy
from source on ARM. Deployment lives in `/opt/clouds` with `clouds_fsw/`,
`clouds_link/`, `spectro/` side by side and **`calibration.json` as a sibling of
`spectro/`** (`_DEFAULT_JSON` resolves to `spectro/../calibration.json`).
Vendor library: `/usr/local/lib/libe9u_LSMD.so` via
`drivers/e9u_LSMD_LIB_Linux/install.sh`.

## Redeploy

`/opt/clouds` is a copy, not a checkout: a fix in the tree changes nothing on
the Pi until it is pushed there, and a partly-updated deployment reads as a bug
in code that is already correct (`docs/TRAPS.md`). Push the three packages, drop
the stale bytecode, restart:

```sh
rsync -av --delete --exclude __pycache__ \
      spectro/ clouds_link/ flight/pi/clouds_fsw/ \
      clouds@192.168.100.10:/opt/clouds/            # one dir per run, or:
scp spectro/*.py clouds@192.168.100.10:/opt/clouds/spectro/
ssh clouds@192.168.100.10 'sudo rm -rf /opt/clouds/*/__pycache__ &&
                           sudo systemctl restart clouds-fsw'
```

Then confirm what is running, not what was sent — `md5sum` the file on both
ends, or grep the deployed copy for the symbol the fix added.
