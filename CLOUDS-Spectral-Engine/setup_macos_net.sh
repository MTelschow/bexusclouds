#!/bin/sh
# CLOUDS bench Ethernet on macOS: this Mac <-> the flight Pi, direct cable.
#
# The counterpart to setup_windows_net.ps1. The link is host-to-host only
# (README, "Bench link to the flight Pi"):
#
#     Mac (ground)     192.168.100.1/24   static, NO router
#     Pi (experiment)  192.168.100.10/24  static, no gateway, eth0
#
# The missing router entry is the whole design, not an omission: with no
# gateway on this service the Mac keeps its normal default route over Wi-Fi,
# so the internet, ssh and brew all keep working with the cable attached.
# Putting 192.168.100.10 in the Router field is the classic mistake here - it
# installs a default route to a Pi that does not forward anything, and the Mac
# loses the internet as soon as this service outranks Wi-Fi in the service
# order.
#
# macOS matters more than Windows here: there is no EURECA vendor library for
# macOS at all, so the detector is *only* ever reachable over this cable
# (`clouds_ui --net`, which is the default on a Mac). No cable, no spectrum.
#
# Ports, from this Mac's point of view:
#     UDP 4000  inbound   telemetry downlink from the Pi
#     TCP 4001  outbound  command uplink to the Pi
#     TCP 4010  outbound  bench frame stream (--net / --bench-stream)
#
#   ./setup_macos_net.sh                      check only, changes nothing
#   ./setup_macos_net.sh --apply              configure it (asks for sudo)
#   ./setup_macos_net.sh --apply --service "USB 10/100/1000 LAN"
#   ./setup_macos_net.sh --revert             put that service back on DHCP
#   ./setup_macos_net.sh --list               just list the network services
set -u

MAC_IP=192.168.100.1
MAC_MASK=255.255.255.0
PI_IP=192.168.100.10
SERVICE=""
MODE=check

ok()   { printf '   [ok]   %s\n' "$*"; }
bad()  { printf '   [FAIL] %s\n' "$*"; }
warn() { printf '   [warn] %s\n' "$*"; }
info() { printf '          %s\n' "$*"; }
head_() { printf '\n== %s\n' "$*"; }

[ "$(uname -s)" = "Darwin" ] || {
    printf '%s\n' "setup_macos_net.sh: this is macOS only." >&2
    printf '%s\n' "  Linux: use nmcli/netplan; Windows: setup_windows_net.ps1" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --apply)   MODE=apply ;;
        --revert)  MODE=revert ;;
        --list)    MODE=list ;;
        --check)   MODE=check ;;
        --service) shift; SERVICE="${1:-}" ;;
        --pi)      shift; PI_IP="${1:-$PI_IP}" ;;
        --ip)      shift; MAC_IP="${1:-$MAC_IP}" ;;
        -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf '%s\n' "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# All enabled services, one per line. A '*' prefix means disabled - those are
# dropped, because configuring a disabled service succeeds and does nothing.
services() {
    networksetup -listallnetworkservices 2>/dev/null | tail -n +2 | grep -v '^\*'
}

# Ethernet-ish services only: Wi-Fi and the VPN/tunnel services that show up in
# the same list are never the bench cable.
wired_services() {
    services | grep -v -i -E '^(Wi-Fi|AirPort|Tailscale|Bluetooth|iPhone|Thunderbolt Bridge)'
}

# Service name -> BSD device. `-listallhardwareports` keys on the *hardware
# port*, which is not the service name: a service can be renamed, and the two
# only coincide by default. `-listnetworkserviceorder` is the mapping that
# actually holds, printing "(n) NAME" followed by "(Hardware Port: ..., Device: enN)".
service_device() {
    networksetup -listnetworkserviceorder 2>/dev/null | awk -v want="$1" '
        /^\([0-9]+\) /{ name = substr($0, index($0, ") ") + 2); next }
        /^\(Hardware Port: /{
            if (name == want) {
                d = $0
                sub(/^.*Device: /, "", d); sub(/\).*$/, "", d)
                gsub(/[ \t]/, "", d)
                if (d != "") print d
                exit
            }
        }'
}

# The service already holding the bench address, if any.
service_with_bench_ip() {
    services | while IFS= read -r s; do
        [ -n "$s" ] || continue
        if networksetup -getinfo "$s" 2>/dev/null | grep -q "^IP address: $MAC_IP$"; then
            printf '%s\n' "$s"
            return 0
        fi
    done
}

# Does this service's device have a cable in it with something on the far end?
# `status: active` on a wired interface means link, which is the one signal
# that tells two identical-looking USB adapters apart.
service_has_link() {
    dev=$(service_device "$1")
    [ -n "$dev" ] || return 1
    ifconfig "$dev" 2>/dev/null | grep -q "status: active"
}

list_services() {
    head_ "network services (enabled)"
    services | while IFS= read -r s; do
        [ -n "$s" ] || continue
        dev=$(service_device "$s")
        ip=$(networksetup -getinfo "$s" 2>/dev/null | awk -F': ' '/^IP address: /{print $2; exit}')
        link="no link"
        service_has_link "$s" && link="LINK UP"
        printf '   %-28s %-8s %-9s %s\n' "$s" "${dev:--}" "$link" "${ip:-no address}"
    done
    printf '\n'
    info "the bench cable is the wired service showing LINK UP."
    info "pass it as --service \"NAME\"."
}

resolve_service() {
    if [ -n "$SERVICE" ]; then
        # Validated at startup, outside any command substitution.
        printf '%s\n' "$SERVICE"
        return 0
    fi
    found=$(service_with_bench_ip)
    if [ -n "$found" ]; then
        printf '%s\n' "$found"
        return 0
    fi
    # Nothing configured yet and no choice made. One wired service is
    # unambiguous; more than one is not, and guessing wrong takes a working
    # adapter off its own network.
    n=$(wired_services | grep -c .)
    if [ "$n" = "1" ]; then
        wired_services
        return 0
    fi
    # Several wired services - the usual case with a dock, or with stale
    # entries for adapters that are not plugged in. Link state separates them:
    # a cable with a powered Pi on the far end is the only one that is active,
    # and an adapter with nothing in it never is. Still only decides when the
    # answer is unique.
    linked=""
    ln=0
    while IFS= read -r s; do
        [ -n "$s" ] || continue
        if service_has_link "$s"; then
            linked="$s"
            ln=$((ln + 1))
        fi
    done <<LINKEOF
$(wired_services)
LINKEOF
    if [ "$ln" = "1" ]; then
        printf '%s\n' "$linked"
        return 0
    fi
    return 1
}

do_check() {
    head_ "adapter"
    svc=$(resolve_service) || svc=""
    if [ -z "$svc" ]; then
        bad "nothing holds $MAC_IP - the Mac side is not configured."
        info "run:  ./setup_macos_net.sh --apply --service \"<name>\""
        list_services
    else
        dev=$(service_device "$svc")
        ok "service \"$svc\" (${dev:-?})"
        cfg=$(networksetup -getinfo "$svc" 2>/dev/null)
        ip=$(printf '%s' "$cfg" | awk -F': ' '/^IP address: /{print $2; exit}')
        rt=$(printf '%s' "$cfg" | awk -F': ' '/^Router: /{print $2; exit}')
        if [ "$ip" = "$MAC_IP" ]; then
            ok "address $ip/$(printf '%s' "$cfg" | awk -F': ' '/^Subnet mask: /{print $2; exit}')"
        else
            bad "address is ${ip:-none}, expected $MAC_IP"
        fi
        case "$rt" in
            ""|"(null)"|"none")
               # Only worth an [ok] once the address is actually set - on an
               # unconfigured service "no router" is true and meaningless.
               [ "$ip" = "$MAC_IP" ] && \
                   ok "no router on this service - default route stays on Wi-Fi" ;;
            *) bad "router is $rt - remove it, or this link steals the default route"
               info "fix: sudo networksetup -setmanual \"$svc\" $MAC_IP $MAC_MASK" ;;
        esac
        if [ -n "$dev" ]; then
            if ifconfig "$dev" 2>/dev/null | grep -q "status: active"; then
                ok "$dev link is up"
            else
                bad "$dev has no link - cable unplugged, or the Pi is off"
            fi
        fi
    fi

    head_ "Pi at $PI_IP"
    if ping -c 2 -t 2 "$PI_IP" >/dev/null 2>&1; then
        rtt=$(ping -c 3 -t 2 "$PI_IP" 2>/dev/null | awk -F'/' '/round-trip/{printf "%.2f", $5}')
        ok "ping replies${rtt:+, ${rtt} ms average}"
    else
        bad "no ping reply"
        info "cable in eth0? Pi powered? On the Pi: ip -4 addr show eth0"
        info "note pi.local resolves to the Wi-Fi address, not this cable -"
        info "address $PI_IP explicitly and check \$SSH_CONNECTION."
    fi
    for pp in "4001:command server:python3 -m clouds_fsw.main --config /etc/clouds/fsw.json" \
              "4010:bench frame stream:python3 -m clouds_fsw.main --bench-stream (or -m spectro.net_server)"
    do
        port=${pp%%:*}; rest=${pp#*:}; label=${rest%%:*}; fix=${rest#*:}
        if nc -z -G 2 "$PI_IP" "$port" >/dev/null 2>&1; then
            ok "TCP $port open - $label"
        else
            warn "TCP $port closed - $label"
            info "on the Pi: $fix"
        fi
    done

    head_ "inbound (UDP 4000 downlink)"
    fw=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)
    case "$fw" in
        *disabled*|*"State = 0"*)
            ok "application firewall is off - nothing blocks the downlink" ;;
        *)
            warn "application firewall is on: $fw"
            blockall=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getblockall 2>/dev/null)
            case "$blockall" in
                *enabled*) bad "block-all-incoming is on - UDP 4000 will never arrive."
                           info "System Settings > Network > Firewall > Options" ;;
                *) info "macOS filters per application, not per port. The first run"
                   info "raises an 'accept incoming connections?' prompt for the"
                   info "python binary - answer Allow. To pre-authorise it:"
                   info "  sudo /usr/libexec/ApplicationFirewall/socketfilterfw \\"
                   info "       --add \"$PWD/.venv/bin/python\" --unblockapp \"$PWD/.venv/bin/python\"" ;;
            esac ;;
    esac

    head_ "listener"
    if lsof -nP -iUDP:4000 2>/dev/null | tail -n +2 | grep -q .; then
        lsof -nP -iUDP:4000 2>/dev/null | tail -n +2 | \
            awk '{printf "   [ok]   UDP 4000 bound by %s (pid %s)\n", $1, $2}'
    else
        info "nothing is listening on UDP 4000 - expected unless the GUI is open."
    fi
    printf '\n'
}

do_apply() {
    svc=$(resolve_service) || {
        printf '\n'
        if wired_services | while IFS= read -r s; do
               service_has_link "$s" && printf 'x'; done | grep -q x
        then
            bad "more than one wired service has a live link - pass --service \"NAME\"."
        else
            bad "no wired service has a live link, so the cable is not in any of"
            bad "them (or the Pi is off). Plug it in, or pass --service \"NAME\"."
        fi
        list_services
        exit 1
    }
    head_ "static address on \"$svc\""
    info "sudo networksetup -setmanual \"$svc\" $MAC_IP $MAC_MASK"
    info "(no router argument - that is deliberate, see the header of this file)"
    if ! sudo networksetup -setmanual "$svc" "$MAC_IP" "$MAC_MASK"; then
        bad "networksetup failed"
        exit 1
    fi
    ok "set $MAC_IP/$MAC_MASK, no router"
    # macOS applies this asynchronously; a check that runs instantly can still
    # see the old address.
    sleep 2
    printf '\nVerifying:\n'
    do_check
}

do_revert() {
    svc=$(resolve_service) || {
        bad "which service? Pass --service \"NAME\"."
        list_services
        exit 1
    }
    head_ "\"$svc\" back to DHCP"
    if sudo networksetup -setdhcp "$svc"; then
        ok "DHCP enabled on \"$svc\""
    else
        bad "networksetup failed"
        exit 1
    fi
    printf '\n'
}

printf '\nCLOUDS Spectral Engine - bench Ethernet (Mac <-> flight Pi)\n'

# Checked here, not inside resolve_service: that runs in a command
# substitution, where anything it prints is captured instead of shown.
if [ -n "$SERVICE" ] && ! services | grep -qx "$SERVICE"; then
    head_ "adapter"
    bad "no enabled network service named \"$SERVICE\"."
    list_services
    printf '\n'
    exit 1
fi

case "$MODE" in
    list)   list_services; printf '\n' ;;
    apply)  do_apply ;;
    revert) do_revert ;;
    *)      do_check ;;
esac
