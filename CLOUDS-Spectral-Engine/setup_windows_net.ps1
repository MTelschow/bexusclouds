<#
.SYNOPSIS
    CLOUDS bench Ethernet: PC <-> flight Pi, direct cable, no switch and no DHCP.

.DESCRIPTION
    The bench link is host-to-host only (docs/BENCH.md, README "Bench setup"):

        PC (ground)      192.168.100.1/24   static, no gateway
        Pi (experiment)  192.168.100.10/24  static, no gateway, eth0

    Neither end has a gateway on purpose, so both machines keep their normal
    default route and WiFi/internet keeps working with the cable attached.
    Windows classifies exactly that kind of gateway-less link as a *Public*
    network, where inbound is blocked by default - which is why the GSE's
    UDP 4000 downlink listener can sit there silently receiving nothing while
    everything else looks correct. That is the failure this script exists for.

    Ports, from the PC's point of view:
        UDP 4000  INBOUND   telemetry downlink from the Pi  (needs a rule)
        TCP 4001  outbound  command uplink to the Pi
        TCP 4010  outbound  bench frame stream (--net / --bench-stream)

.PARAMETER Check
    Report the link and change nothing. This is the default.

.PARAMETER Apply
    Set the static address and add the firewall rule. Needs an elevated shell.

.PARAMETER Revert
    Put the adapter back on DHCP and remove the rule. Needs an elevated shell.

.PARAMETER InterfaceAlias
    Which adapter the cable is in, e.g. "Ethernet". Omitted with -Apply, the
    script lists the candidates and stops rather than guessing: picking the
    wrong adapter takes the machine off its own network.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup_windows_net.ps1
    powershell -ExecutionPolicy Bypass -File setup_windows_net.ps1 -Apply -InterfaceAlias Ethernet
    powershell -ExecutionPolicy Bypass -File setup_windows_net.ps1 -Revert -InterfaceAlias Ethernet
#>
[CmdletBinding(DefaultParameterSetName = 'Check')]
param(
    [Parameter(ParameterSetName = 'Check')] [switch] $Check,
    [Parameter(ParameterSetName = 'Apply')] [switch] $Apply,
    [Parameter(ParameterSetName = 'Revert')] [switch] $Revert,
    [string] $InterfaceAlias,
    [string] $PcAddress  = '192.168.100.1',
    [string] $PiAddress  = '192.168.100.10',
    [int]    $PrefixLength = 24
)

$ErrorActionPreference = 'Stop'
$RuleName = 'CLOUDS downlink (UDP 4000)'

function Write-Head($t) { Write-Host ''; Write-Host "== $t" -ForegroundColor Cyan }
function Write-Ok($t)   { Write-Host "   [ok]   $t" -ForegroundColor Green }
function Write-Bad($t)  { Write-Host "   [FAIL] $t" -ForegroundColor Red }
function Write-Warn2($t){ Write-Host "   [warn] $t" -ForegroundColor Yellow }
function Write-Info($t) { Write-Host "          $t" -ForegroundColor DarkGray }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-EthernetCandidates {
    Get-NetAdapter -Physical |
        Where-Object { $_.MediaType -ne 'Native 802.11' } |
        Sort-Object -Property @{ Expression = { $_.Status -ne 'Up' } }, Name
}

function Resolve-Adapter {
    param([string] $Alias, [switch] $Required)
    if ($Alias) {
        $a = Get-NetAdapter -Name $Alias -ErrorAction SilentlyContinue
        if (-not $a) { throw "no adapter named '$Alias'. Candidates: " +
                             ((Get-EthernetCandidates).Name -join ', ') }
        return $a
    }
    # No alias: the one already carrying the bench address is unambiguous.
    $ip = Get-NetIPAddress -IPAddress $PcAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Select-Object -First 1
    if ($ip) { return Get-NetAdapter -InterfaceIndex $ip.InterfaceIndex }
    if ($Required) {
        Write-Host ''
        Write-Bad "which adapter is the cable in? Pass -InterfaceAlias."
        Write-Host ''
        Get-EthernetCandidates |
            Format-Table -AutoSize Name, Status, LinkSpeed, InterfaceDescription |
            Out-Host
        Write-Info "e.g.  -Apply -InterfaceAlias '$((Get-EthernetCandidates | Select-Object -First 1).Name)'"
        throw 'no adapter selected'
    }
    return $null
}

function Invoke-Check {
    Write-Head 'adapter'
    $ad = Resolve-Adapter -Alias $InterfaceAlias
    if (-not $ad) {
        Write-Bad "no adapter holds $PcAddress - the PC side is not configured."
        Write-Info "run:  -Apply -InterfaceAlias <name>"
        Get-EthernetCandidates | Format-Table -AutoSize Name, Status, LinkSpeed | Out-Host
    } else {
        if ($ad.Status -eq 'Up') { Write-Ok "$($ad.Name) is up ($($ad.LinkSpeed))" }
        else { Write-Bad "$($ad.Name) is $($ad.Status) - cable unplugged, or the Pi is off" }

        $ip = Get-NetIPAddress -InterfaceIndex $ad.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue
        $bench = $ip | Where-Object { $_.IPAddress -eq $PcAddress }
        if ($bench) { Write-Ok "address $PcAddress/$($bench.PrefixLength) ($($bench.PrefixOrigin))" }
        else {
            Write-Bad "$($ad.Name) does not hold $PcAddress"
            foreach ($a in $ip) { Write-Info "has $($a.IPAddress)/$($a.PrefixLength) ($($a.PrefixOrigin))" }
        }

        $prof = Get-NetConnectionProfile -InterfaceIndex $ad.ifIndex -ErrorAction SilentlyContinue
        if ($prof) {
            if ($prof.NetworkCategory -eq 'Public') {
                Write-Warn2 "network profile is Public - inbound is blocked by default."
                Write-Info  "expected on a gateway-less link; the UDP 4000 rule below is what fixes it."
            } else { Write-Ok "network profile is $($prof.NetworkCategory)" }
        }
    }

    Write-Head "Pi at $PiAddress"
    if (Test-Connection -ComputerName $PiAddress -Count 2 -Quiet -ErrorAction SilentlyContinue) {
        Write-Ok "ping replies"
    } else {
        Write-Bad "no ping reply"
        Write-Info "cable in eth0? Pi powered? On the Pi: ip -4 addr show eth0"
        Write-Info "note pi.local resolves to the WiFi address, not this cable."
    }
    foreach ($p in @(@{n='command server'; port=4001}, @{n='bench frame stream'; port=4010})) {
        $r = Test-NetConnection -ComputerName $PiAddress -Port $p.port -WarningAction SilentlyContinue
        if ($r.TcpTestSucceeded) { Write-Ok "TCP $($p.port) open - $($p.n)" }
        else {
            Write-Warn2 "TCP $($p.port) closed - $($p.n)"
            if ($p.port -eq 4001) { Write-Info "start the flight app on the Pi: python3 -m clouds_fsw.main --config /etc/clouds/fsw.json" }
            else { Write-Info "--net needs a server: clouds_fsw.main --bench-stream, or python3 -m spectro.net_server" }
        }
    }

    Write-Head 'inbound firewall (UDP 4000 downlink)'
    $rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if ($rule -and $rule.Enabled -eq 'True' -and $rule.Action -eq 'Allow') {
        Write-Ok "'$RuleName' present and enabled"
    } else {
        $py = Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue |
              Where-Object { $_.Program -like '*python*' } |
              ForEach-Object { $_ | Get-NetFirewallRule -ErrorAction SilentlyContinue } |
              Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' -and $_.Enabled -eq 'True' }
        if ($py) {
            Write-Warn2 "no port rule, but $($py.Count) inbound Allow rule(s) exist for python.exe."
            Write-Info  "those cover the interpreter that was allowed, not every one - a venv"
            Write-Info  "python.exe is a different program to Windows. Prefer the port rule: -Apply"
        } else {
            Write-Bad "nothing allows inbound UDP 4000 - the downlink will never arrive."
            Write-Info "run:  -Apply    (elevated)"
        }
    }

    Write-Head 'listener'
    $l = Get-NetUDPEndpoint -LocalPort 4000 -ErrorAction SilentlyContinue
    if ($l) {
        foreach ($e in $l) {
            $proc = (Get-Process -Id $e.OwningProcess -ErrorAction SilentlyContinue).ProcessName
            Write-Ok "UDP $($e.LocalAddress):4000 bound by $proc (pid $($e.OwningProcess))"
        }
    } else {
        Write-Info "nothing is listening on UDP 4000 right now - expected unless the GUI is open."
    }
    Write-Host ''
}

function Invoke-Apply {
    if (-not (Test-Admin)) { throw 'run this in an elevated PowerShell (Run as administrator).' }
    $ad = Resolve-Adapter -Alias $InterfaceAlias -Required

    Write-Head "static address on $($ad.Name)"
    $have = Get-NetIPAddress -InterfaceIndex $ad.ifIndex -IPAddress $PcAddress `
                             -AddressFamily IPv4 -ErrorAction SilentlyContinue
    if ($have) {
        Write-Ok "$PcAddress/$($have.PrefixLength) already set"
    } else {
        # A static address disables DHCP on this adapter - that is the point,
        # and Invoke-Revert puts it back.
        New-NetIPAddress -InterfaceIndex $ad.ifIndex -IPAddress $PcAddress `
                         -PrefixLength $PrefixLength | Out-Null
        Write-Ok "set $PcAddress/$PrefixLength (DHCP now off on this adapter)"
    }
    # No gateway and no DNS on purpose: the default route stays on WiFi.
    Set-NetIPInterface -InterfaceIndex $ad.ifIndex -AddressFamily IPv4 -Dhcp Disabled -ErrorAction SilentlyContinue

    Write-Head 'firewall'
    if (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue) {
        Set-NetFirewallRule -DisplayName $RuleName -Enabled True -Action Allow
        Write-Ok "'$RuleName' already present - enabled"
    } else {
        New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Protocol UDP `
                            -LocalPort 4000 -Action Allow -Profile Any `
                            -Description 'CLOUDS/BEXUS 38 telemetry downlink from the experiment Pi.' | Out-Null
        Write-Ok "added '$RuleName' (inbound UDP 4000, all profiles)"
    }

    Write-Host ''
    Write-Host 'Done. Verifying:' -ForegroundColor Cyan
    Invoke-Check
}

function Invoke-Revert {
    if (-not (Test-Admin)) { throw 'run this in an elevated PowerShell (Run as administrator).' }
    $ad = Resolve-Adapter -Alias $InterfaceAlias -Required

    Write-Head "$($ad.Name) back to DHCP"
    Remove-NetIPAddress -InterfaceIndex $ad.ifIndex -IPAddress $PcAddress `
                        -Confirm:$false -ErrorAction SilentlyContinue
    Set-NetIPInterface -InterfaceIndex $ad.ifIndex -AddressFamily IPv4 -Dhcp Enabled
    Write-Ok "removed $PcAddress, DHCP enabled"

    Write-Head 'firewall'
    if (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue) {
        Remove-NetFirewallRule -DisplayName $RuleName
        Write-Ok "removed '$RuleName'"
    } else { Write-Info "'$RuleName' was not present" }
    Write-Host ''
}

Write-Host ''
Write-Host 'CLOUDS Spectral Engine - bench Ethernet (PC <-> flight Pi)' -ForegroundColor White

switch ($PSCmdlet.ParameterSetName) {
    'Apply'  { Invoke-Apply }
    'Revert' { Invoke-Revert }
    default  { Invoke-Check }
}
