"""Host-side decoder for tools/encoder_trace_probe.c output.

Capture the probe's USB CDC text with cdc_capture.py (same directory), then:

    python flight/mcu/src/tools/encoder_trace_analyse.py trace.txt

Per capture it prints, for each of GP19..GP22: edge count, edge rate, duty,
median period and the rpm that implies for a 1024-line channel; how many
bits flip per transition (a line and its complement always flip together, a
clean quadrature pair never does); each pair's level-at-edge relation; and
every ordered pair judged as A/B quadrature (fraction of valid Gray steps).
The 2026-09-28 findings this produced are in docs/HARDWARE.md (encoder row).
"""
import sys
from collections import Counter, defaultdict

PINS = [19, 20, 21, 22]
caps = {}
cur = None
for line in open(sys.argv[1]):
    f = line.split()
    if not f:
        continue
    if f[0] == "C":
        cur = f[1]
        caps[cur] = {"iters": int(f[2]), "us": int(f[3]), "n": int(f[4]), "tr": []}
    elif f[0] == "T" and cur:
        caps[cur]["tr"].append((int(f[1]), int(f[2], 16)))
    elif f[0] == "static":
        print("static state", f[1])

for name, c in caps.items():
    tr = c["tr"]
    print(f"\n== {name}: {len(tr)} transitions, {c['iters']} iters in {c['us']} us", end="")
    if not tr or c["iters"] == 0:
        print(" (nothing)")
        continue
    ns_per_iter = c["us"] * 1000.0 / c["iters"]
    span_us = (tr[-1][0] - tr[0][0]) * ns_per_iter / 1000.0
    print(f", {ns_per_iter:.1f} ns/iter, trace spans {span_us:.0f} us")

    # per-line edges, duty, period
    edges = Counter(); rise = defaultdict(list); high_iters = Counter()
    prev_i, prev_s = tr[0]
    for i, s in tr[1:]:
        d = s ^ prev_s
        for b in range(4):
            if d >> b & 1:
                edges[b] += 1
                if s >> b & 1:
                    rise[b].append(i)
            if prev_s >> b & 1:
                high_iters[b] += i - prev_i
        prev_i, prev_s = i, s
    total = tr[-1][0] - tr[0][0]
    for b in range(4):
        gp = PINS[b]
        if edges[b] == 0:
            print(f"  GP{gp}: static")
            continue
        per = None
        if len(rise[b]) > 2:
            gaps = [j - i for i, j in zip(rise[b], rise[b][1:])]
            gaps.sort()
            per = gaps[len(gaps) // 2] * ns_per_iter / 1000.0
        duty = 100.0 * high_iters[b] / total if total else 0
        rate = edges[b] / (span_us / 1e6) if span_us else 0
        rpm = rate * 60 / 2048
        print(f"  GP{gp}: {edges[b]} edges, {rate/1000:.1f} k edges/s, duty {duty:.1f} % high, "
              f"median period {per and round(per,2)} us -> {rpm:.0f} rpm if 1024-line")

    # simultaneous flips and pairwise relations
    multi = Counter()
    for (i0, s0), (i1, s1) in zip(tr, tr[1:]):
        multi[bin(s0 ^ s1).count("1")] += 1
    print("  bits flipped per transition:", dict(multi))
    live = [b for b in range(4) if edges[b] > 20]
    for a in live:
        for b in live:
            if a >= b:
                continue
            # value of b at rising and falling edges of a
            at_rise = Counter(); at_fall = Counter(); together = 0
            prev_s = tr[0][1]
            for _, s in tr[1:]:
                d = s ^ prev_s
                if d >> a & 1:
                    if d >> b & 1:
                        together += 1
                    elif s >> a & 1:
                        at_rise[s >> b & 1] += 1
                    else:
                        at_fall[s >> b & 1] += 1
                prev_s = s
            tot = together + sum(at_rise.values()) + sum(at_fall.values())
            print(f"  GP{PINS[a]} vs GP{PINS[b]}: flip together {100*together/tot:.0f} %; "
                  f"at GP{PINS[a]} rise GP{PINS[b]}=1 {100*at_rise[1]/max(1,sum(at_rise.values())):.0f} %; "
                  f"at fall GP{PINS[b]}=1 {100*at_fall[1]/max(1,sum(at_fall.values())):.0f} %")
    # quadrature check on each ordered pair: count valid gray steps
    for a in live:
        for b in live:
            if a == b:
                continue
            ok = bad = 0; direction = Counter()
            prev_s = tr[0][1]
            for _, s in tr[1:]:
                pa, pb = prev_s >> a & 1, prev_s >> b & 1
                na, nb = s >> a & 1, s >> b & 1
                if (pa, pb) == (na, nb):
                    prev_s = s; continue
                if pa != na and pb != nb:
                    bad += 1
                else:
                    ok += 1
                    old = (pa << 1) | pb; new = (na << 1) | nb
                    fwd = {0: 1, 1: 3, 3: 2, 2: 0}
                    direction["+" if fwd[old] == new else "-"] += 1
                prev_s = s
            if ok + bad:
                print(f"  as quadrature A=GP{PINS[a]} B=GP{PINS[b]}: valid steps {100*ok/(ok+bad):.1f} %, "
                      f"direction {dict(direction)}")
