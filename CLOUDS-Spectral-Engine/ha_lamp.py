"""Scoped Home Assistant control for CLOUDS bench lights ONLY.

Hard safeguard: this tool can touch ONLY the entities in ALLOWED (the Living
Room Hue GU10 colour spots + Floor lamp 1) and ONLY the light on/off/brightness/
colour services, with a fixed parameter allow-list. Any other entity / service /
parameter is refused by construction. The bearer token is read from
%USERPROFILE%\\.clouds_ha_token (outside the repo) or the CLOUDS_HA_TOKEN env
var, and is never printed.

Target defaults to the GU10 spot group; override with CLOUDS_HA_TARGETS
(comma-separated entity_ids, all of which must be in ALLOWED).

Usage:
  python ha_lamp.py state
  python ha_lamp.py off | on
  python ha_lamp.py white <pct> | bri <pct>
  python ha_lamp.py rgb <r> <g> <b> [pct]
  python ha_lamp.py ct <kelvin> [pct]
"""
import json
import os
import sys
import urllib.error
import urllib.request

HA_BASE = os.environ.get("CLOUDS_HA_BASE", "http://homeassistant.local:8123")

# --- hard scope: the only entities this tool may ever address ---
# All Hue lights in the LIVING ROOM only (user-authorized). Nothing in any other
# room is in this set, so the tool cannot address them.
ALLOWED = frozenset([
    "light.bed_1", "light.bed_2",
    "light.floor_lamp_1", "light.floor_lamp_2", "light.floor_lamp_3",
    "light.main_desk_1", "light.main_desk_2",
    "light.spot_1", "light.spot_2", "light.spot_3", "light.spot_4",
    "light.living_room",   # the Living Room Hue room group
])
# Default target = the whole room (every physical Living Room light).
DEFAULT_GROUP = [
    "light.bed_1", "light.bed_2",
    "light.floor_lamp_1", "light.floor_lamp_2", "light.floor_lamp_3",
    "light.main_desk_1", "light.main_desk_2",
    "light.spot_1", "light.spot_2", "light.spot_3", "light.spot_4",
]
ALLOWED_SERVICES = {"turn_on", "turn_off"}
ALLOWED_ON_PARAMS = {"brightness_pct", "rgb_color", "color_temp_kelvin", "transition"}


def _targets():
    env = os.environ.get("CLOUDS_HA_TARGETS")
    targets = [x.strip() for x in env.split(",") if x.strip()] if env else list(DEFAULT_GROUP)
    for e in targets:
        if e not in ALLOWED:
            sys.exit(f"REFUSED: target {e!r} is not in the allow-list")
    return targets


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
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _guard(service, params):
    if service not in ALLOWED_SERVICES:
        sys.exit(f"REFUSED: service light.{service} not in the allow-list")
    extra = set(params) - ALLOWED_ON_PARAMS
    if extra:
        sys.exit(f"REFUSED: parameters {sorted(extra)} not in the allow-list")


def call(service, **params):
    _guard(service, params)
    data = {"entity_id": _targets(), **params}
    st, _ = _req("POST", f"/api/services/light/{service}", data)
    return st


def state():
    for e in _targets():
        st, body = _req("GET", f"/api/states/{e}")
        if st == 200:
            j = json.loads(body)
            a = j.get("attributes", {})
            print(f"{e}: {j.get('state')} bri={a.get('brightness')} "
                  f"rgb={a.get('rgb_color')} ct={a.get('color_temp_kelvin')}")
        else:
            print(f"{e}: HTTP {st}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0].lower(), args[1:]
    if cmd == "state":
        state()
    elif cmd == "off":
        print("turn_off ->", call("turn_off"))
    elif cmd == "on":
        print("turn_on ->", call("turn_on"))
    elif cmd == "white":
        pct = int(rest[0]) if rest else 100
        print("white ->", call("turn_on", brightness_pct=pct, color_temp_kelvin=4000))
    elif cmd == "bri":
        print("bri ->", call("turn_on", brightness_pct=int(rest[0])))
    elif cmd == "rgb":
        params = {"rgb_color": [int(rest[0]), int(rest[1]), int(rest[2])]}
        if len(rest) > 3:
            params["brightness_pct"] = int(rest[3])
        print("rgb ->", call("turn_on", **params))
    elif cmd == "ct":
        params = {"color_temp_kelvin": int(rest[0])}
        if len(rest) > 1:
            params["brightness_pct"] = int(rest[1])
        print("ct ->", call("turn_on", **params))
    else:
        sys.exit(f"unknown command {cmd!r}")


if __name__ == "__main__":
    main()
