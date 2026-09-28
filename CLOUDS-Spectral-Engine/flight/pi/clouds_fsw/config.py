"""FSW-PI configuration - JSON-overridable dataclass."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, fields

from clouds_link.linkrate import DOWNLINK_AVG_BIT_S, DOWNLINK_PEAK_BIT_S
from spectro.driver import resolve_kind

#: Keys an older /etc/clouds/fsw.json may still carry. They are dropped with
#: a warning rather than refused, because a config the Pi cannot load is a
#: service that crash-loops at the next deploy.
RETIRED_KEYS = {
    "budget_kbit_s": "replaced by downlink_avg_kbit_s / downlink_peak_kbit_s "
                     "(2026-09-29)",
}


@dataclass
class FswConfig:
    # E-Link (Table 6-3): UDP downlink target + TCP command port
    ground_host: str = "192.168.100.1"
    ground_port: int = 4000
    cmd_bind: str = "0.0.0.0"
    cmd_port: int = 4001
    # UART to the RP2350
    uart_port: str = "/dev/ttyAMA0"
    uart_baud: int = 115200
    # How long a command may wait for the MCU's ACK before it is reported to
    # ground as rejected. The MCU answers from its 10 ms loop, so this is
    # slack, not a budget; it must stay well under the GSE's own 3 s timeout.
    mcu_ack_timeout_s: float = 1.0
    # storage (O.3, S.6-style rotation)
    data_dir: str = "/data/clouds"
    rotate_s: int = 600
    flush_every: int = 10          # records between forced flushes
    # acquisition (P.3)
    spectro_kind: str = "std"      # "std" = the Duo; the only flight detector
    sample_interval_s: float = 1.0
    exposure_us: int = 100_000     # fixed flight default (P-09)
    auto_exposure: bool = False    # optional guard servo
    reconnect_s: float = 5.0       # spectrometer retry period (P-10)
    # telemetry (O.4 downlink subset)
    # Transmitted spectra per second - the one knob that spends downlink;
    # acquisition (sample_interval_s) and exposure_us are independent of it.
    # 1 Hz is a cadence choice, not a limit: the whole flight mix - a
    # quick-look cycle of 164 B (both channels), HK 96 B, PISTATUS every
    # 10 s, all +42 B of headers per datagram - is ~3.2 kbit/s on the wire
    # against the 100 kbit/s E-Link average (tests/test_fsw_telemetry.py::
    # TestDownlinkBudget keeps the arithmetic honest).
    quicklook_interval_s: float = 1.0
    quicklook_bin: int = 8
    pistatus_interval_s: float = 10.0
    timesync_interval_s: float = 10.0   # S.4
    # E-Link downlink limits the shaper enforces (clouds_link.linkrate):
    # average over 60 s and peak over 1 s, on the wire. The defaults are the
    # link's; lower them on the bench to watch the shaper drop quick-look.
    downlink_avg_kbit_s: float = DOWNLINK_AVG_BIT_S / 1000.0     # 100
    downlink_peak_kbit_s: float = DOWNLINK_PEAK_BIT_S / 1000.0   # 400
    # liveness
    mcu_silent_alarm_s: float = 10.0    # spec: MCU silent > 10 s -> alarm
    mock: bool = False
    calibration_path: str | None = None

    @classmethod
    def load(cls, path: str | None = None, **overrides) -> "FswConfig":
        data: dict = {}
        if path:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.update(overrides)
        for key, why in RETIRED_KEYS.items():
            if key in data:
                print(f"fsw config: ignoring retired key {key!r} - {why}",
                      file=sys.stderr)
                del data[key]
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        cfg = cls(**data)
        resolve_kind(cfg.spectro_kind)   # fail at load, not at first connect
        return cfg
