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
#   The interpreter must be one the pinned requirements have wheels for.
#   `python3` on a current Mac is whatever Homebrew last upgraded to - 3.14
#   today - and numpy 2.2.6 has no cp314 wheel, so a plain
#   `python3 -m pip install -r requirements.txt` fails on a version solve, or
#   worse starts building numpy and scipy from source. The supported window is
#   Python 3.11-3.13 (see PY_MIN/PY_MAX below).
#
# On a machine with no environment yet this builds one: it picks a base
# interpreter in that window, creates the repo-local .venv, and installs
# requirements.txt into it. Nothing outside ./.venv is touched and nothing is
# ever installed into a system interpreter - `rm -rf .venv` undoes all of it.
# Set CLOUDS_NO_SETUP=1 to skip that and fail with the commands instead.
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
#   ./run_clouds_ui.sh --mock                   no hardware at all
#   ./run_clouds_ui.sh --help                   the full flag list
#
# The cable itself is ./setup_macos_net.sh - run that first on a fresh Mac.
#
# Environment:
#   CLOUDS_PYTHON    use exactly this interpreter, skip all discovery
#   CLOUDS_NO_SETUP  1 = never create a venv or install anything
set -e

cd "$(dirname "$0")"

# The window the pinned requirements.txt actually has wheels for: scipy 1.16
# needs >= 3.11, and numpy 2.2.6 / matplotlib 3.10.8 ship no cp314 wheels.
# Widen this when the pins move, not before - a too-new interpreter does not
# fail cleanly, it falls back to building numpy and scipy from source.
PY_MIN_MINOR=11
PY_MAX_MINOR=13
VENV=.venv
VENV_PY="$VENV/bin/python"
REQ=requirements.txt

# Every import the window needs before it can draw anything. Checked as a set,
# because a half-installed venv (pip killed part-way) is otherwise indistinguishable
# from a complete one until the app is already up.
DEPS="PyQt5, matplotlib, numpy, scipy"

say()  { printf '%s\n' "$*"; }
err()  { printf '%s\n' "$*" >&2; }

# Does this interpreter run at all? A .venv whose base Python was upgraded or
# uninstalled by Homebrew still *has* a bin/python - a dangling symlink, or one
# that dies in dyld. That is the common macOS breakage and it must not be read
# as "the venv is fine".
py_works() { [ -n "$1" ] && [ -x "$1" ] && "$1" -c '' 2>/dev/null; }

py_has_deps() { "$1" -c "import $DEPS" 2>/dev/null; }

# Is this interpreter inside the supported version window?
py_in_window() {
    "$1" - "$PY_MIN_MINOR" "$PY_MAX_MINOR" 2>/dev/null <<'PYEOF'
import sys
lo, hi = int(sys.argv[1]), int(sys.argv[2])
sys.exit(0 if sys.version_info[0] == 3 and lo <= sys.version_info[1] <= hi else 1)
PYEOF
}

py_version() { "$1" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null; }

# A base interpreter to build the venv from. Newest-supported first, and the
# usual macOS install roots are searched by path as well as by PATH: a
# python.org or pyenv install is often not on PATH at all, and finding it is
# the difference between "run one brew command" and "this is unsupported".
find_base_python() {
    minor=$PY_MAX_MINOR
    while [ "$minor" -ge "$PY_MIN_MINOR" ]; do
        for cand in \
            "$(command -v python3.$minor 2>/dev/null || true)" \
            "/opt/homebrew/bin/python3.$minor" \
            "/usr/local/bin/python3.$minor" \
            "/Library/Frameworks/Python.framework/Versions/3.$minor/bin/python3" \
            "$HOME/.pyenv/versions/3.$minor.0/bin/python3"
        do
            if py_works "$cand" && py_in_window "$cand"; then
                printf '%s\n' "$cand"
                return 0
            fi
        done
        # pyenv patch releases: 3.13.2, 3.13.7, ...
        for cand in "$HOME"/.pyenv/versions/3.$minor.*/bin/python3; do
            if py_works "$cand" && py_in_window "$cand"; then
                printf '%s\n' "$cand"
                return 0
            fi
        done
        minor=$((minor - 1))
    done
    # Last resort: a bare python3 that happens to land in the window anyway.
    cand="$(command -v python3 2>/dev/null || true)"
    if py_works "$cand" && py_in_window "$cand"; then
        printf '%s\n' "$cand"
        return 0
    fi
    return 1
}

no_interpreter() {
    err "run_clouds_ui.sh: no Python 3.$PY_MIN_MINOR-3.$PY_MAX_MINOR found."
    bare="$(command -v python3 2>/dev/null || true)"
    if [ -n "$bare" ]; then
        err "  python3 here is $(py_version "$bare") ($bare), which is outside"
        err "  the window requirements.txt has wheels for - numpy and scipy would"
        err "  be built from source, or the solve would simply fail."
    fi
    case "$(uname -s)" in
        Darwin) err "  brew install python@3.$PY_MAX_MINOR" ;;
        *)      err "  install python3.$PY_MAX_MINOR from your distribution" ;;
    esac
    err "  then re-run this script - it builds ./$VENV itself."
    exit 1
}

build_venv() {
    base="$1"
    say "run_clouds_ui.sh: no usable environment yet - building ./$VENV"
    say "  base interpreter: $base ($(py_version "$base"))"
    say "  nothing outside ./$VENV is touched; 'rm -rf $VENV' undoes this."
    say
    rm -rf "$VENV"
    "$base" -m venv "$VENV" || {
        err "run_clouds_ui.sh: '$base -m venv $VENV' failed."
        err "  on Debian/Ubuntu: sudo apt install python3-venv"
        exit 1
    }
}

install_requirements() {
    say "run_clouds_ui.sh: installing $REQ into ./$VENV (first run is slow)"
    say
    # --upgrade pip first: the venv ships whatever pip the base interpreter
    # bundled, and an old resolver picks source distributions over wheels.
    "$VENV_PY" -m pip install --quiet --upgrade pip setuptools wheel || true
    if ! "$VENV_PY" -m pip install -r "$REQ"; then
        err
        err "run_clouds_ui.sh: pip install failed."
        err "  environment: $VENV_PY ($(py_version "$VENV_PY")), $(uname -m)"
        err "  retry by hand to see the full output:"
        err "      $VENV_PY -m pip install -r $REQ"
        err "  or start over:  rm -rf $VENV && ./run_clouds_ui.sh"
        exit 1
    fi
    say
}

# -- pick the interpreter ----------------------------------------------------
PY=""
SETUP_ALLOWED=1
[ "${CLOUDS_NO_SETUP:-0}" = "1" ] && SETUP_ALLOWED=0

if [ -n "${CLOUDS_PYTHON:-}" ]; then
    # An explicit choice is taken as given and never rebuilt underneath.
    py_works "$CLOUDS_PYTHON" || {
        err "run_clouds_ui.sh: CLOUDS_PYTHON=$CLOUDS_PYTHON does not run."
        exit 1
    }
    PY="$CLOUDS_PYTHON"
elif py_works "$VENV_PY"; then
    PY="$VENV_PY"
elif [ -d "$VENV" ]; then
    # The directory is there but its python does not run - a base Python that
    # moved or was upgraded away leaves bin/python as a dangling symlink, and
    # `[ -e ]` follows the link, so it must be the *directory* that is tested.
    err "run_clouds_ui.sh: ./$VENV is broken (its base interpreter is gone)."
    if [ "$SETUP_ALLOWED" = "1" ]; then
        err "  rebuilding it."
        err
        base="$(find_base_python)" || no_interpreter
        build_venv "$base"
        install_requirements
        PY="$VENV_PY"
    else
        err "  rm -rf $VENV && ./run_clouds_ui.sh"
        exit 1
    fi
elif [ -n "${VIRTUAL_ENV:-}" ] && py_works "$VIRTUAL_ENV/bin/python"; then
    # An activated venv is the operator's, not ours: use it, never modify it.
    PY="$VIRTUAL_ENV/bin/python"
elif [ "$SETUP_ALLOWED" = "1" ]; then
    base="$(find_base_python)" || no_interpreter
    build_venv "$base"
    install_requirements
    PY="$VENV_PY"
else
    err "run_clouds_ui.sh: no ./$VENV and CLOUDS_NO_SETUP=1."
    err "  python3 -m venv $VENV && $VENV_PY -m pip install -r $REQ"
    exit 1
fi

# -- dependencies ------------------------------------------------------------
# Fail with the fix rather than with a traceback. PyQt5 is the one dependency
# that is routinely missing (no wheel for the newest CPython), and matplotlib
# is checked with it because the spectrum view is useless without it.
if ! py_has_deps "$PY"; then
    missing=$("$PY" - <<'PYEOF' 2>/dev/null
import importlib.util
print(" ".join(m for m in ("PyQt5", "matplotlib", "numpy", "scipy")
                if not importlib.util.find_spec(m)))
PYEOF
)
    if [ "$PY" = "$VENV_PY" ] && [ "$SETUP_ALLOWED" = "1" ]; then
        say "run_clouds_ui.sh: ./$VENV is missing ${missing:-some dependencies}"
        if ! py_in_window "$PY"; then
            # Installing into it would just fail the same solve again.
            err "  and it is Python $(py_version "$PY"), outside the supported"
            err "  3.$PY_MIN_MINOR-3.$PY_MAX_MINOR window - rebuilding it."
            err
            base="$(find_base_python)" || no_interpreter
            build_venv "$base"
        fi
        install_requirements
    else
        err "run_clouds_ui.sh: $PY cannot import ${missing:-$DEPS}."
        err "  $PY -m pip install -r $REQ"
        if [ -n "${VIRTUAL_ENV:-}" ] && [ "$PY" = "$VIRTUAL_ENV/bin/python" ]; then
            err "  (this is your activated venv, \$VIRTUAL_ENV - left alone on"
            err "   purpose. 'deactivate' first to let this script build ./$VENV.)"
        fi
        exit 1
    fi
    py_has_deps "$PY" || {
        err "run_clouds_ui.sh: still cannot import $DEPS after installing."
        exit 1
    }
fi

# Apple Silicon: an x86_64 interpreter under Rosetta resolves x86_64 wheels,
# which then cannot load beside an arm64 Qt. It reads as a corrupt install.
HOST_ARCH="$(uname -m)"
PY_ARCH="$("$PY" -c 'import platform;print(platform.machine())' 2>/dev/null || echo "$HOST_ARCH")"
if [ "$PY_ARCH" != "$HOST_ARCH" ]; then
    err "run_clouds_ui.sh: warning - this Mac is $HOST_ARCH but $PY is $PY_ARCH"
    err "  (running under Rosetta). Mixed-architecture wheels fail at import."
    err "  rm -rf $VENV and re-run from a native shell if Qt misbehaves."
fi

export PYTHONPATH=".:gse:flight/pi${PYTHONPATH:+:$PYTHONPATH}"

# -- the cable ---------------------------------------------------------------
# macOS has no vendor driver, so the detector default is the bench Pi over the
# cable. If that link is down the app opens and then sits in a reconnect loop
# with the reason buried in a status label - so say it here, once, where the
# fix is one line away. Never fatal: --flight and --no-link do not need it, and
# neither does an operator who is about to plug the cable in.
BENCH_PI="${CLOUDS_SPECTRO_HOST:-192.168.100.10}"
BENCH_PI_HOST="${BENCH_PI%%:*}"
case " $* " in
    *" --flight "*|*" --no-link "*|*" --net "*|*" --mock "*|*" --help "*|*" -h "*) ;;
    *)
        if [ "$(uname -s)" = "Darwin" ] && \
           ! ping -c 1 -t 1 "$BENCH_PI_HOST" >/dev/null 2>&1; then
            err "run_clouds_ui.sh: warning - no reply from $BENCH_PI_HOST,"
            err "  which is where the detector is from a Mac (no vendor driver here)."
            err "      ./setup_macos_net.sh              check the cable"
            err "      ./setup_macos_net.sh --apply      configure it"
            err "  Or start without a detector:  ./run_clouds_ui.sh --flight"
            err
        fi
        ;;
esac

say "CLOUDS operator interface  -  $PY ($(py_version "$PY"))"
case " $* " in
    *" --mock "*)
        say "  MOCK: synthetic detector, plus a simulated Pi and RP2350 on loopback."
        say "        Nothing on this screen is a measurement." ;;
esac
say "  instrument + flight in one window; pick the Spectrum source in the sidebar."
say "  session logs: ./gse_sessions (override with --log-dir)"
say

# exec: the window becomes this process, so Ctrl-C and a window close both end
# the same thing and no shell lingers behind it.
exec "$PY" -u -m clouds_ui "$@"
