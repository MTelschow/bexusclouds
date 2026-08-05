#!/usr/bin/env python3
"""Build a standalone executable for the CLOUDS Spectral Engine bench panel.

    pip install pyinstaller
    python build_exe.py

PyInstaller does not cross-compile - this builds for whichever OS you run it
on, into dist/. On Windows it bundles the vendor Duo DLL (vendor/) for the
local `std` driver; on macOS/Linux there is no native driver (see README),
so only --net <pi-ip> and --mock work, same as running from source.

No --windowed: the console stays visible on purpose. PyQt5 aborts the whole
process on an unhandled exception in a slot (see CLAUDE.md), and that
console is often the only place a field operator sees the traceback - same
reasoning as run_clouds_spectral.bat.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "CLOUDS_Spectral_Engine"


def main() -> None:
    try:
        import PyInstaller.__main__
    except ImportError:
        raise SystemExit(
            "PyInstaller is not installed in this environment.\n"
            "Install it first:  pip install pyinstaller"
        )

    # bundled alongside the script so HERE-relative loading (assets/,
    # calibration*.json, vendor/) resolves the same way frozen as it does
    # from source - see _default_calibration() / eureca_driver.py's _lib_dir()
    data_files = [
        ("assets", "assets"),
        ("vendor", "vendor"),
        ("calibration.json", "."),
        ("calibration_edu.json", "."),
        ("calibration_single.json", "."),
    ]
    args = [
        os.path.join(HERE, "clouds_spectral.py"),
        "--name", NAME,
        "--onefile",
        "--noconfirm",
        "--collect-data", "matplotlib",
    ]
    for src, dst in data_files:
        src_path = os.path.join(HERE, src)
        if os.path.exists(src_path):
            args += ["--add-data", f"{src_path}{os.pathsep}{dst}"]

    if sys.platform == "win32":
        ico = os.path.join(HERE, "assets", "clouds.ico")
        if os.path.exists(ico):
            args += ["--icon", ico]

    PyInstaller.__main__.run(args)

    exe = f"{NAME}.exe" if sys.platform == "win32" else NAME
    print(f"\nBuilt dist/{exe}")
    if sys.platform != "win32":
        print("No native detector driver ships for this OS - "
             "run with --net <pi-ip> or --mock.")


if __name__ == "__main__":
    main()
