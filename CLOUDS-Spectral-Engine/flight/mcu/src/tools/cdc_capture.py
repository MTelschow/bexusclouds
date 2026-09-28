"""Read a bench probe's USB CDC output into a file until its "=== done"
marker. Start it BEFORE `picotool load`: it retries opening /dev/cu.usbmodem*
while the carrier reboots and reopens if the port vanishes under it (the old
image's port dies on reflash - docs/TRAPS.md). Needs pyserial.

    python flight/mcu/src/tools/cdc_capture.py trace.txt [idle_timeout_s]
"""
import glob, sys, time
import serial

out = sys.argv[1]
idle_limit = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
deadline = time.time() + 40
port = None
while time.time() < deadline and port is None:
    for dev in sorted(glob.glob("/dev/cu.usbmodem*")):
        try:
            port = serial.Serial(dev, 115200, timeout=1)
            print("opened", dev, file=sys.stderr)
            break
        except Exception as e:
            time.sleep(0.3)
    if port is None:
        time.sleep(0.5)
if port is None:
    sys.exit("no CDC port")
last = time.time()
lines = 0
with open(out, "w") as fh:
    while True:
        try:
            line = port.readline()
        except Exception as e:
            print("read error, reopening:", e, file=sys.stderr)
            time.sleep(1.5)
            port = None
            while port is None:
                for dev in sorted(glob.glob("/dev/cu.usbmodem*")):
                    try:
                        port = serial.Serial(dev, 115200, timeout=1); break
                    except Exception:
                        time.sleep(0.3)
                time.sleep(0.3)
            continue
        if line:
            last = time.time()
            txt = line.decode("utf-8", "replace")
            fh.write(txt)
            lines += 1
            if txt.startswith("H ") or txt.startswith("C ") or txt.startswith("==="):
                print(txt.rstrip(), file=sys.stderr)
            if txt.startswith("=== done"):
                break
        elif time.time() - last > idle_limit:
            print("idle timeout", file=sys.stderr)
            break
print("lines", lines, file=sys.stderr)
