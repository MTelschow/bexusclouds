"""FSW-PI configuration - JSON-overridable dataclass."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields

from spectro.driver import resolve_kind


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
    spectro_kind: str = "std"      # "std" = Duo (flight), "edu" = single-channel
    sample_interval_s: float = 1.0
    exposure_us: int = 100_000     # fixed flight default (P-09)
    auto_exposure: bool = False    # optional guard servo
    reconnect_s: float = 5.0       # spectrometer retry period (P-10)
    # telemetry (O.4 downlink subset)
    # Transmitted spectra per second - this is the only knob that spends
    # downlink budget; acquisition (sample_interval_s) and exposure_us are
    # independent of it. 1.0 s is the budget maximum: a quick-look cycle is
    # 164 B (both channels), so 1 Hz = 1.31 kbit/s on top of HK (60 B @ 1 Hz =
    # 0.48) and PISTATUS (0.02) -> 1.81 kbit/s against the 2 kbit/s continuous
    # E-Link limit. Guarded by tests/test_fsw_telemetry.py::TestDownlinkBudget.
    quicklook_interval_s: float = 1.0
    quicklook_bin: int = 8
    pistatus_interval_s: float = 10.0
    timesync_interval_s: float = 10.0   # S.4
    budget_kbit_s: float = 2.0          # continuous-stream watch level
    # liveness
    mcu_silent_alarm_s: float = 10.0    # spec: MCU silent > 10 s -> alarm
    # Ground interlock (S.10) as defence in depth: RELEASE is refused unless
    # the MCU's housekeeping says the experiment is flying. Set true only for
    # a bench rehearsal with no CaCO3 loaded - it is logged loudly when it is.
    allow_ground_release: bool = False
    mock: bool = False
    calibration_path: str | None = None

    @classmethod
    def load(cls, path: str | None = None, **overrides) -> "FswConfig":
        data: dict = {}
        if path:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.update(overrides)
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        cfg = cls(**data)
        resolve_kind(cfg.spectro_kind)   # fail at load, not at first connect
        return cfg
