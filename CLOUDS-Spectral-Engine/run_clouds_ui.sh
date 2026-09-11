#!/bin/sh
# Launch the CLOUDS operator interface on macOS / Linux.
#
# The POSIX counterpart to run_clouds_spectral.bat, and it exists for one
# reason: the interpreter and PYTHONPATH are both easy to get wrong, and both
# fail in ways that look like the app being broken.
#
#   PYTHONPATH needs three entries - the repo root for clouds_link/ and
#   spectro/, gse/ for clouds_gse, flight/pi/ for clouds_fsw. Miss one and you
#   get an ImportError naming a package that is plainly sitting right there.
#
#   The interpreter must be the repo venv. A system python3 that is newer than
#   the venv typically has no PyQt5 wheel available, so `python3 -m clouds_ui`
#   fails on the Qt import with nothing to say about why.
#
# Every argument is passed straight through to `python -m clouds_ui`, so this
# adds no flags of its own and invents no defaults - the one default that does
# exist lives in the app: on macOS, which has no EURECA vendor library at all,
# the detector defaults to the bench Pi over the cable (192.168.100.10, moved
# by CLOUDS_SPECTRO_HOST), because "this machine" is not somewhere the
# detector can be here.
#
#   ./run_clouds_ui.sh                          the Duo on this machine;
#                                               on macOS, the Duo on the Pi
#   ./run_clouds_ui.sh --no-link                instrument only, no downlink
#   ./run_clouds_ui.sh --net 192.168.100.10     detector on the Pi, explicitly
#   ./run_clouds_ui.sh --flight                 ground station, downlink only
#   ./run_clouds_ui.sh --help                   the full flag list
set -e

cd "$(dirname "$0")"

# The venv first; a bare python3 only as a fallback, and it is checked below
# rather than left to fail on an import.
if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PY="$VIRTUAL_ENV/bin/python"
else
    PY="$(command -v python3 || true)"
fi

if [ -z "$PY" ]; then
    echo "run_clouds_ui.sh: no Python found." >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

export PYTHONPATH=".:gse:flight/pi${PYTHONPATH:+:$PYTHONPATH}"

# Fail with the fix rather than with a traceback. PyQt5 is the one dependency
# that is routinely missing (no wheel for the newest CPython), and matplotlib
# is checked with it because the spectrum view is useless without it.
if ! "$PY" -c "import PyQt5, matplotlib" 2>/dev/null; then
    echo "run_clouds_ui.sh: $PY cannot import PyQt5 / matplotlib." >&2
    echo "  $PY -m pip install -r requirements.txt" >&2
    echo "  (PyQt5 has no wheel for the newest CPython - use the repo venv:" >&2
    echo "   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" >&2
    exit 1
fi

echo "CLOUDS operator interface  -  $PY"
echo "  instrument + flight in one window; pick the Spectrum source in the sidebar."
echo "  session logs: ./gse_sessions (override with --log-dir)"
echo

# exec: the window becomes this process, so Ctrl-C and a window close both end
# the same thing and no shell lingers behind it.
exec "$PY" -u -m clouds_ui "$@"
