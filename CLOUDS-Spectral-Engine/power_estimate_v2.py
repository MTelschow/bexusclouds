"""Refreshed 'how many watts does the spectrometer need?' estimate, anchored to the
REAL measured sources (Hue floor lamp + actual sunlight via the roller shutter), in the
current config (red caps on). Order-of-magnitude, but now cross-checked three ways.
"""
import os
import numpy as np
from spectro import processing as P
from spectro.calibration import Calibration

H, C = 6.62607015e-34, 299792458.0
GAIN = 1.36            # e-/count (firmware CG)
READ_E = 46.0         # e- (firmware RN / measured ~28-46)
QE = 0.30             # TCD1304 bare-Si QE near 700 nm (no microlens)
LAM = 700e-9
EPH = H * C / LAM
HERE = os.path.dirname(os.path.abspath(__file__))


def med3(a):
    b = a.astype(float).copy()
    b[1:-1] = np.median(np.stack([a[:-2], a[1:-1], a[2:]]), axis=0)
    return b


def counts_to_Wdet(counts, t):
    return (counts * GAIN / QE) * EPH / t            # power at the detector plane


def snr10_signal_e():
    k = 10.0
    return (k**2 + np.sqrt(k**4 + 4 * k**2 * READ_E**2)) / 2.0


# ---------- anchor A: real sunlight ----------
d = np.load(os.path.join(HERE, "output", "shutter_char.npz"), allow_pickle=True)
nm, win = d["wavelengths"], d["ch_window"].astype(int)
dark = P._despike(d["dark"].astype(float))[win]
i100 = list(d["positions"]).index(100)
exp = float(d["spectra_exp"][i100]); t = exp / 1000.0
spec = med3(P._despike(d["spectra"][i100].astype(float))[win] - dark)   # continuum, spikes removed
band = (nm >= 600) & (nm < 851)
peak_c = float(spec[band].max())
tot_c = float(spec[band].clip(0).sum())
npix = int(band.sum())
peak_e = peak_c * GAIN
snr_peak = peak_e / np.sqrt(peak_e + READ_E**2)
Pdet_tot = counts_to_Wdet(tot_c, t)
print("ANCHOR A - real sunlight (WNW window, ~18:40 June, 100% shutter, red caps):")
print(f"  {exp:g} ms: continuum peak {peak_c:.0f} counts (SNR/px ~{snr_peak:.0f}); band total {tot_c:.0f} counts")
print(f"  -> power at DETECTOR over the lit band = {Pdet_tot*1e9:.3f} nW")
print(f"  -> at the FIBRE input (throughput 0.05/0.10/0.20) = "
      f"{Pdet_tot/0.05*1e9:.2f} / {Pdet_tot/0.10*1e9:.2f} / {Pdet_tot/0.20*1e9:.2f} nW")
# scale the measured SNR down to the SNR=10 'works well' threshold (shot-limited: SNR ~ sqrt(P*t))
floor_frac = (10.0 / snr_peak)**2
print(f"  sunlight runs ~{snr_peak/10:.0f}x above the SNR=10 floor at {exp:g} ms")
print(f"  -> implied per-band FLOOR at the fibre (thr 0.10) ~ {Pdet_tot/0.10*floor_frac*1e12:.1f} pW  (at {exp:g} ms)")

# ---------- anchor B: Hue floor lamp ----------
try:
    dl = np.load(os.path.join(HERE, "output", "power_estimate.npz"), allow_pickle=True)
    Lf = dl["light_frames"][-1]
    lamp_spec = med3(P._despike(np.median(Lf, axis=0))[win])
    lamp_peak = float(lamp_spec[band].max())
    # the lamp run's top exposure
    lexp = float(dl["exposures_us"][-1]) / 1e6
    le = lamp_peak * GAIN
    lsnr = le / np.sqrt(le + READ_E**2)
    print(f"\nANCHOR B - Hue floor lamp: peak {lamp_peak:.0f} counts @ {lexp*1e3:.0f} ms (SNR/px ~{lsnr:.0f}); "
          f"~{lsnr/10:.0f}x above floor")
except Exception as e:
    print("\nANCHOR B - lamp data unavailable:", e)

# ---------- anchor C: detector physics (independent of any source) ----------
S = snr10_signal_e()
print("\nANCHOR C - detector physics (gain+QE+read noise only):")
for tt, lab in ((0.01, "10 ms"), (0.1, "100 ms"), (1.0, "1 s")):
    Ppix = (S / QE) * EPH / tt
    print(f"  SNR=10/px @ {lab:5}: {Ppix*1e15:6.1f} fW/px @det | "
          f"~{Ppix*npix*1e12:5.2f} pW/band @det | ~{Ppix*npix/0.10*1e12:6.1f} pW/band @fibre (thr 0.10)")

print("\nCONSENSUS: minimum to 'work well' (SNR~10, red band, ~100 ms) is single-digit to")
print("tens of pW at the fibre; ~nW gives a strong spectrum. Sunlight here already delivers")
print(f"~{Pdet_tot/0.10*1e9:.1f} nW (~{int(snr_peak/10)}x the floor) and the LCU ~2.5 mW (~1e5-1e8x).")
