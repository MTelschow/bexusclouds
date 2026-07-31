"""Scoped Home Assistant control for the CLOUDS bench ROLLER SHUTTER only.

Hard safeguard: this tool can address ONLY cover.rolladen and ONLY the
open/close/stop/set-position services. Any other entity or service is refused by
construction. The bearer token is read from %USERPROFILE%\\.clouds_ha_token (or
CLOUDS_HA_TOKEN) and is never printed.

  python ha_cover.py state
  python ha_cover.py open | close | stop
  python ha_cover.py position <pct>          (0 = closed, 100 = open)
"""
import json
import os
import sys
import urllib.error
import urllib.request

HA_BASE = os.environ.get("CLOUDS_HA_BASE", "http://homeassistant.local:8123")

# --- hard scope: the only cover this tool may ever address ---
TARGET = "cover.rolladen"
ALLOWED = frozenset([TARGET])
ALLOWED_SERVICES = {"open_cover", "close_cover", "stop_cover", "set_cover_position"}
ALLOWED_PARAMS = {"position"}


def _token():
    t = os.environ.get("CLOUDS_HA_TOKEN")
    if not t:
        path = os.path.join(os.path.expanduser("~"), ".clouds_ha_token")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                t = f.read().strip()
    if not t:
        sys.exit("no HA token (set CLOUDS_HA_TOKEN or write ~/.clouds_ha_token)")
    return t


def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HA_BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _token())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def call(service, **params):
    if service not in ALLOWED_SERVICES:
        sys.exit(f"REFUSED: service cover.{service} not in the allow-list")
    extra = set(params) - ALLOWED_PARAMS
    if extra:
        sys.exit(f"REFUSED: parameters {sorted(extra)} not in the allow-list")
    st, _ = _req("POST", f"/api/services/cover/{service}", {"entity_id": TARGET, **params})
    return st


def state():
    st, body = _req("GET", f"/api/states/{TARGET}")
    if st == 200:
        j = json.loads(body)
        print(f"{TARGET}: {j.get('state')} position={j.get('attributes', {}).get('current_position')}")
    else:
        print(f"{TARGET}: HTTP {st}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0].lower(), args[1:]
    if cmd == "state":
        state()
    elif cmd == "open":
        print("open ->", call("open_cover"))
    elif cmd == "close":
        print("close ->", call("close_cover"))
    elif cmd == "stop":
        print("stop ->", call("stop_cover"))
    elif cmd == "position":
        print("position ->", call("set_cover_position", position=int(rest[0])))
    else:
        sys.exit(f"unknown command {cmd!r}")


if __name__ == "__main__":
    main()
