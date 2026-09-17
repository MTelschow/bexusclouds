"""Bench check for the membrane position switch on GP30 (HKV_MEMBRANE_PULLED).

Drives the membrane from the ground side and watches the sensed plunger bit
in housekeeping through three phases:

  1. off      - MEMBRANE 0: the switch must never read pulled
  2. driving  - MEMBRANE <duty>: every packet must carry MEMBRANE_CYCLING,
                the MCU's "the switch changed state since the last HK" latch.
                The instantaneous PULLED bit is one fixed-phase sample of the
                2 Hz cycle (HK and wave share the MCU loop) and is printed but
                not judged. No CYCLING under a drive = plunger not moving.
  3. off      - MEMBRANE 0 again: back to never pulled, never cycling

It also refuses to pass if HKE_NO_MEMBRANE_SENSE is set: that means the MCU
is running a pico2 (RP2350A) build with GP30 compiled out, not carrier
firmware. Exit code 0 only when all three phases hold.

    python membrane_sense_check.py                    # Pi at 192.168.100.10
    python membrane_sense_check.py --experiment 127.0.0.1   # against --mock

Needs PYTHONPATH to include the repo root and gse/ (see CLAUDE.md), and no
other GSE/GUI listening on the downlink port.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

from clouds_gse.commander import Commander
from clouds_gse.receiver import Receiver
from clouds_link.frames import AckResult
from clouds_link.hk import HkErrors, Housekeeping, ValveStatus


class Phase:
    def __init__(self, name: str) -> None:
        self.name = name
        self.samples: list[bool | None] = []
        self.cycling: list[bool | None] = []
        self.unsourced = 0

    def add(self, h: Housekeeping) -> None:
        if h.error_flags & HkErrors.NO_MEMBRANE_SENSE:
            self.unsourced += 1
        self.samples.append(h.membrane_pulled)
        self.cycling.append(h.membrane_cycling)

    @property
    def pulled(self) -> int:
        return sum(1 for s in self.samples if s is True)

    @property
    def moving(self) -> int:
        return sum(1 for c in self.cycling if c is True)

    @property
    def n(self) -> int:
        return len(self.samples)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--experiment", default="192.168.100.10")
    ap.add_argument("--cmd-port", type=int, default=4001)
    ap.add_argument("--listen", type=int, default=4000)
    ap.add_argument("--duty", type=int, default=60)
    ap.add_argument("--packets", type=int, default=20,
                    help="HK packets per phase (1 Hz)")
    args = ap.parse_args()

    phases = [Phase("off"), Phase(f"driving {args.duty} %"), Phase("off again")]
    current: list[Phase | None] = [None]
    lock = threading.Lock()

    def on_hk(frame, h: Housekeeping) -> None:
        with lock:
            ph = current[0]
        text = h.membrane_text
        if h.error_flags & HkErrors.NO_MEMBRANE_SENSE:
            text += "   ** NO_MEMBRANE_SENSE: GP30 not in this MCU build **"
        print(f"  hk seq={frame.seq:5d} state={h.state_name:10s} "
              f"membrane={text:22s} driving={h.actuator_text}")
        if ph is not None:
            ph.add(h)

    rx = Receiver(port=args.listen, on_hk=on_hk)
    rx.start()
    cmd = Commander(args.experiment, args.cmd_port, timeout=3.0)
    if not cmd.connected:
        print(f"no command link to {args.experiment}:{args.cmd_port}")
        rx.stop()
        return 2

    def wait_hk(timeout: float = 8.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if rx.last_hk is not None and time.time() - rx.last_hk_time < 3:
                return True
            time.sleep(0.2)
        return False

    print(f"waiting for housekeeping from {args.experiment} ...")
    if not wait_hk():
        print("no HK on the downlink - is the FSW running and the Pi's "
              "ground_host this machine?")
        cmd.close()
        rx.stop()
        return 2

    def collect(ph: Phase) -> None:
        with lock:
            current[0] = ph
        start = ph.n
        t0 = time.time()
        while ph.n - start < args.packets and time.time() - t0 < args.packets * 3:
            time.sleep(0.2)
        with lock:
            current[0] = None

    ok = True
    try:
        for i, ph in enumerate(phases):
            duty = args.duty if i == 1 else 0
            r = cmd.membrane(duty)
            print(f"\n== {ph.name}: MEMBRANE {duty} -> {r.name}")
            if r != AckResult.OK:
                print("   command refused - MCU state does not allow the drive "
                      "(TERMINATION/SAFE?), cannot test")
                ok = False
                break
            time.sleep(1.5)  # let the first HK after the command reflect it
            collect(ph)
    finally:
        try:
            cmd.membrane(0)
        finally:
            cmd.close()
            rx.stop()

    print("\n== verdict")
    for i, ph in enumerate(phases):
        if ph.n == 0:
            print(f"  {ph.name:14s} no packets            FAIL")
            ok = False
            continue
        frac = ph.pulled / ph.n
        if ph.unsourced:
            line, good = "HKE_NO_MEMBRANE_SENSE set: pico2 build, GP30 absent", False
        elif i == 1:
            # Motion is the judgement. The position is one fixed-phase sample
            # of the 2 Hz cycle and is reported only.
            good = ph.moving == ph.n
            line = (f"cycling {ph.moving}/{ph.n}, pulled {ph.pulled}/{ph.n} "
                    f"({frac:3.0%}, duty {args.duty} %)")
            if not good:
                line += "  plunger NOT moving on %d packet(s)" % (ph.n - ph.moving)
        else:
            good = ph.pulled == 0 and ph.moving == 0
            line = f"pulled {ph.pulled}/{ph.n}, cycling {ph.moving}/{ph.n}"
            if not good:
                line += "  switch active with the drive OFF"
        print(f"  {ph.name:14s} {line:50s} {'ok' if good else 'FAIL'}")
        ok = ok and good
    print("\nMEMBRANE SENSE", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
