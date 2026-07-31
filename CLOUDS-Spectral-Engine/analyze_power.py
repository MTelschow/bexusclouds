"""Radiometric analysis of output/power_estimate.npz (corruption-robust).

The raw stream corrupts a random ~9% of pixels each frame to a fixed code (~33514
counts). We reject those samples per pixel, then:
  - conversion gain g [e-/count] from the photon-transfer slope  var = signal/g
  - full-well [e-], read+dark noise floor [e- and counts]
  - source responsivity [e-/s/pixel]
  - MINIMUM DETECTABLE OPTICAL POWER at detector and (via throughput) at fibre input.

Datasheet inputs are CLI-overridable so radiometry can be refreshed without re-measuring:
    python analyze_power.py --qe 0.15 --throughput 0.10 --snr 10 --lam 660 --gain 1.5
(--gain overrides the measured photon-transfer gain with a datasheet value.)
"""
import argparse
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
NPZ = os.path.join(HERE, "output", "power_estimate.npz")
H, C = 6.62607015e-34, 299792458.0
SAT = 65520
CORRUPT_LO, CORRUPT_HI = 32900, 34200     # the fixed glitch code band
MINN = 15                                 # min clean samples to trust a pixel


def masked(S):
    """Replace corrupted samples with NaN. S:(M,2048) -> float (M,2048)."""
    Sc = S.astype(float)
    Sc[(S >= CORRUPT_LO) & (S <= CORRUPT_HI)] = np.nan
    return Sc


def stats(Sc):
    n = np.isfinite(Sc).sum(0).astype(float)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(Sc, axis=0)
        var = np.nanvar(Sc, axis=0, ddof=1)
    ok = n >= MINN
    return np.where(ok, mean, np.nan), np.where(ok, var, np.nan), n


def flicker_correct(Sc):
    """Divide out common-mode (global, multiplicative) source flicker per frame,
    using the brightest pixels as the per-frame brightness reference."""
    with np.errstate(invalid="ignore"):
        med = np.nanmedian(Sc, axis=0)
        thr = np.nanpercentile(med, 90)
        ref = np.isfinite(med) & (med > thr)
        sf = np.nanmean(Sc[:, ref], axis=1)        # per-frame brightness
        sf = sf / np.nanmean(sf)                    # normalise ~1
    return Sc / sf[:, None], float(np.nanstd(sf))


def clean_stats(S, correct_flicker=False):
    Sc = masked(S)
    amp = 0.0
    if correct_flicker:
        Sc, amp = flicker_correct(Sc)
    m, v, n = stats(Sc)
    return m, v, n, amp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qe", type=float, default=0.15)
    ap.add_argument("--throughput", type=float, default=0.10)
    ap.add_argument("--snr", type=float, default=10.0)
    ap.add_argument("--lam", type=float, default=660.0)
    ap.add_argument("--int_ms", type=float, default=100.0)
    ap.add_argument("--gain", type=float, default=None, help="override measured gain [e-/count]")
    args = ap.parse_args()

    d = np.load(NPZ, allow_pickle=True)
    exps = d["exposures_us"].astype(float)
    L, D = d["light_frames"], d["dark_frames"]            # (Lvl, M, 2048)
    nlvl = len(exps)

    lm = np.empty((nlvl, 2048)); lv = np.empty((nlvl, 2048)); ln = np.empty((nlvl, 2048))
    dm = np.empty((nlvl, 2048)); dv = np.empty((nlvl, 2048)); dn = np.empty((nlvl, 2048))
    flick = []
    for i in range(nlvl):
        lm[i], lv[i], ln[i], a = clean_stats(L[i], correct_flicker=True)
        dm[i], dv[i], dn[i], _ = clean_stats(D[i], correct_flicker=False)
        flick.append(a)
    print(f"source flicker amplitude (removed) ~ {100*np.median(flick):.1f}% rms per frame")

    corrupt_frac = np.mean([(np.mean((L[i] >= CORRUPT_LO) & (L[i] <= CORRUPT_HI))) for i in range(nlvl)])
    base = np.isfinite(dm[0]) & (dm[0] < 6000) & (dn[0] >= MINN)
    dstd0 = np.sqrt(dv[0])
    print(f"corrupted-sample fraction ~ {100*corrupt_frac:.1f}% per frame (rejected)")
    print(f"clean dark baseline (median) = {np.median(dm[0][base]):.0f} counts")
    print(f"clean read+dark noise: median per-pixel std = {np.median(dstd0[base]):.1f} counts "
          f"(usable pixels {int(base.sum())})")

    # --- photon transfer on clean stats ---
    sig = lm - dm
    shot = lv - dv
    xs, ys = [], []
    for i in range(nlvl):
        sel = base & np.isfinite(sig[i]) & (sig[i] > 1500) & (sig[i] < 50000) \
            & (shot[i] > 0) & (ln[i] >= 30) & (dn[i] >= 30)
        xs.append(sig[i][sel]); ys.append(shot[i][sel])
    x = np.concatenate(xs); y = np.concatenate(ys)
    ratio = y / x                       # = 1/gain per point
    g_med = 1.0 / np.median(ratio)
    g_ls = np.sum(x * x) / np.sum(x * y)
    gain = args.gain if args.gain else g_med
    print(f"\nPHOTON TRANSFER (n={x.size} clean points)")
    print(f"  measured gain: median={g_med:.2f}  LS={g_ls:.2f}  e-/count"
          + (f"   [OVERRIDDEN -> {gain:.2f}]" if args.gain else ""))

    full_well = SAT * gain
    read_counts = float(np.median(dstd0[base]))
    read_e = read_counts * gain
    print(f"  gain used  = {gain:.2f} e-/count")
    print(f"  full well  = {full_well:,.0f} e-")
    print(f"  read+dark noise floor = {read_e:.0f} e-  ({read_counts:.1f} counts)")

    # dark-current slope over the swept exposures
    dmg = np.array([np.nanmedian(dm[i][base]) for i in range(nlvl)])
    dc = np.polyfit(exps / 1e6, dmg, 1)[0]
    print(f"  dark-current slope ~ {dc*gain:,.0f} e-/s/pixel (small/flat over 9-114 ms)")

    # --- responsivity under floor_lamp_1 warm 100% ---
    pk = base & (sig[-1] > 0.4 * SAT)
    if pk.sum() < 3:
        pk = base & (sig[-1] > np.nanpercentile(sig[-1][base], 99))
    rate_c = np.nanmedian([np.polyfit(exps / 1e6, sig[:, p], 1)[0] for p in np.where(pk)[0]])
    print(f"\nSOURCE RESPONSE ({int(pk.sum())} brightest px): "
          f"{rate_c:,.0f} counts/s = {rate_c*gain:,.0f} e-/s/pixel at peak")

    # --- detection limit -> optical power ---
    Eph = H * C / (args.lam * 1e-9)
    t = args.int_ms / 1000.0
    n_dark_e = np.sqrt(read_e**2 + max(dc * gain, 0) * t)
    k = args.snr
    S_min = (k**2 + np.sqrt(k**4 + 4 * k**2 * n_dark_e**2)) / 2.0   # e- per pixel
    photons = S_min / args.qe
    P_pix = photons * Eph / t                                      # W on one pixel
    n_band = int(base.sum())
    P_det = P_pix * n_band
    P_fib = P_det / args.throughput
    print(f"\nDETECTION LIMIT (SNR={k:.0f}/px, t={args.int_ms:.0f} ms, QE={args.qe}, "
          f"throughput={args.throughput}, lam={args.lam}nm)")
    print(f"  noise/px           = {n_dark_e:.0f} e-")
    print(f"  min signal/px      = {S_min:.0f} e- = {photons:.0f} photons")
    print(f"  power on one pixel = {P_pix*1e12:.3f} pW")
    print(f"  at DETECTOR ({n_band} px) = {P_det*1e9:.2f} nW = {P_det*1e6:.4f} uW")
    print(f"  at FIBRE input     = {P_fib*1e9:.1f} nW = {P_fib*1e6:.3f} uW  (/{args.throughput})")
    print(f"  vs LCU ~2.5 mW peak -> headroom ~{2.5e-3/P_fib:,.0f}x")

    out = {"gain_e_per_count": gain, "gain_measured_median": g_med, "gain_measured_ls": g_ls,
           "full_well_e": full_well, "read_noise_e": read_e, "read_noise_counts": read_counts,
           "dark_baseline_counts": float(np.median(dm[0][base])),
           "corrupt_frac_pct": 100 * corrupt_frac, "resp_e_per_s_peakpx": rate_c * gain,
           "n_pixels": n_band, "params": vars(args),
           "P_pixel_detector_pW": P_pix * 1e12, "P_band_detector_nW": P_det * 1e9,
           "P_fibre_input_nW": P_fib * 1e9}
    with open(os.path.join(HERE, "output", "power_estimate_result.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("\nsaved: output/power_estimate_result.json")


if __name__ == "__main__":
    main()
