"""Enumerate the EURECA DLL's API surface to see (a) what else we can read from the
sensor and (b) whether any firmware-write / flash / erase capability exists at all.

Exported symbol names live as ASCII inside the PE file, so a byte scan is reliable
and dependency-free; pefile (if present) gives the precise export table too.
"""
import os
import re

DLL = os.environ.get("CLOUDS_E9U_DLL",
                     r"C:\Users\kai-w\projects\EURECA_e9u\e9u_LSMD_GTK_x64\libe9u_LSMD_x64.dll")

data = open(DLL, "rb").read()
print(f"DLL: {DLL}\nsize: {len(data):,} bytes\n")

# all e9u_LSMD_* symbols referenced anywhere in the binary
names = sorted(set(m.decode("ascii") for m in re.findall(rb"e9u_LSMD_[A-Za-z0-9_]+", data)))
print(f"{len(names)} distinct e9u_LSMD_* symbols:")
for n in names:
    print("   ", n)

# precise export table via pefile, if available
try:
    import pefile
    pe = pefile.PE(DLL, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
    exp = sorted(e.name.decode() for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name)
    print(f"\npefile: {len(exp)} EXPORTED functions:")
    for n in exp:
        print("   ", n)
except Exception as e:
    print(f"\n(pefile not available: {e}; the byte-scan list above is the reference)")

# classify by intent -- is anything able to MODIFY the device?
DANGER = ["flash", "erase", "program", "firmware", "bootload", "boot_load", "update",
          "write", "burn", "fpga", "bitstream", "reflash", "wipe"]
READISH = ["read", "get", "search", "start", "next_frame", "pixel", "eeprom", "set_times",
           "stop", "close", "disconnect", "open", "info", "version", "serial", "temp"]
print("\n--- API intent classification (on e9u_LSMD_* symbols) ---")
danger = [n for n in names if any(k in n.lower() for k in DANGER)]
print("WRITE/FLASH/ERASE-capable symbols:", danger if danger else "NONE FOUND")
print("set/config symbols:", [n for n in names if n.lower().count("set") or "eeprom" in n.lower()])

# broad sweep for firmware-update machinery anywhere in the binary (not just our prefix)
print("\n--- raw tokens anywhere in the DLL ---")
for kw in (b"flash", b"erase", b"firmware", b"bootloader", b"\\.bit", b"bitstream",
           b"FT_EraseEE", b"FT_WriteEE", b"FT_Write", b"FT_Read", b"eeprom_write",
           b"temperature", b"trigger", b"gpio"):
    n = len(re.findall(re.escape(kw), data, re.I))
    if n:
        print(f"   {kw.decode('latin1'):16} x{n}")
