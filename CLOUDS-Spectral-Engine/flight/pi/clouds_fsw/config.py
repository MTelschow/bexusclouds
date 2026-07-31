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
    quicklook_interval_s: float = 30.0
    quicklook_bin: int = 8
    pistatus_interval_s: float = 10.0
    timesync_interval_s: float = 10.0   # S.4
    budget_kbit_s: float = 2.0          # continuous-stream watch level
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
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        cfg = cls(**data)
        resolve_kind(cfg.spectro_kind)   # fail at load, not at first connect
        return cfg
