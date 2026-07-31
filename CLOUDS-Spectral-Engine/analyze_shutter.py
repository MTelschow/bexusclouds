"""Glitch-cleaned analysis of the daylight / roller-shutter run (output/shutter_char.npz).

The live bench prints were glitch-contaminated (peak = a residual spike). Here we clean
each saved frame (spatial despike), then extract: daylight spectrum shape vs opening,
exposure-normalised signal, a look for an O2 A-band (~760 nm) dip, and a glitch-rejecting
photon-transfer gain + the REAL intra-stack drift (was the daylight steady?).
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from spectro import processing as P
from spectro.calibration import Calibration

HERE = os.path.dirname(os.path.abspath(__file__))
d = np.load(os.path.join(HERE, "output", "shutter_char.npz"), allow_pickle=True)
pos, spectra, exps, curs = d["positions"], d["spectra"], d["spectra_exp"], d["spectra_cur"]
dark, nm, win = d["dark"], d["wavelengths"], d["ch_window"].astype(int)
cal = Calibration.load(); ch = cal.by_role("measurement")
BANDS = [("blue", 384, 500), ("green", 500, 600), ("red", 600, 750), ("nir", 750, 851)]

dark_c = P._despike(dark.astype(float))[win]
clean = {int(p): P._despike(spectra[i].astype(float))[win] - dark_c for i, p in enumerate(pos)}

print("=== daylight spectrum vs shutter opening (red caps on, dark-subtracted, despiked) ===")
for i, p in enumerate(pos):
    sig = clean[int(p)]
    pk = int(np.argmax(sig))
    row = "  ".join(f"{b} {sig[(nm >= lo) & (nm < hi)].sum():8.0f}" for b, lo, hi in BANDS)
    print(f"  {p:3d}% (real {curs[i]}) exp {exps[i]:g}ms  peak {sig[pk]:7.0f} @ {nm[pk]:.0f}nm | {row}")

print("\n=== exposure-normalised red-band signal vs opening (counts/ms) ===")
for i, p in enumerate(pos):
    red = clean[int(p)][(nm >= 600) & (nm < 750)].sum() / exps[i]
    print(f"  {p:3d}% open -> {red:9.0f} counts/ms")

# brightest spectrum: look for an O2 A-band dip near 760 nm
best = max(clean, key=lambda p: clean[p].max())
fb = clean[best]
nir = (nm >= 740) & (nm <= 790)
if nir.sum() > 3:
    seg_nm, seg = nm[nir], fb[nir]
    dip = int(np.argmin(seg))
    print(f"\n=== NIR look (best = {best}% open) ===")
    print(f"  min in 740-790 nm at {seg_nm[dip]:.0f} nm = {seg[dip]:.0f} "
          f"(vs ~{np.median(seg):.0f} median) -> {'possible O2/water dip' if seg[dip] < 0.85*np.median(seg) else 'no clear dip at this resolution'}")

# --- photon-transfer gain, glitch-rejected, + REAL drift ---
exps_ptc, F = d["ptc_exps"], d["ptc_frames"]      # F: (L, M, 2048)
darkc_full = P._despike(dark.astype(float))


def clean_stats(S):
    Sc = S.astype(float).copy()
    for k in range(Sc.shape[0]):
        Sc[k][P._glitch_mask(Sc[k])] = np.nan
    n = np.isfinite(Sc).sum(0)
    with np.errstate(invalid="ignore"):
        return np.nanmean(Sc, 0), np.nanvar(Sc, 0, ddof=1), n


lm = np.zeros((len(exps_ptc), 2048)); lv = np.zeros_like(lm); drift = []
for i in range(len(exps_ptc)):
    lm[i], lv[i], n = clean_stats(F[i])
    gm = [np.nanmean(np.where(P._glitch_mask(F[i][k]), np.nan, F[i][k])) for k in range(F[i].shape[0])]
    drift.append(float(np.nanstd(gm) / np.nanmean(gm) * 100))

read_var = float(np.nanmedian(lv[0][(lm[0] > 1400) & (lm[0] < 1700)]))   # baseline pixels
sig = lm - darkc_full
xs, ys = [], []
for i in range(len(exps_ptc)):
    sel = np.isfinite(sig[i]) & np.isfinite(lv[i]) & (sig[i] > 3000) & (sig[i] < 45000) & (lv[i] > read_var)
    xs.append(sig[i][sel]); ys.append(lv[i][sel] - read_var)
x, y = np.concatenate(xs), np.concatenate(ys)
gain = float(np.median(x / y))
print("\n=== daylight photon-transfer gain (glitch-rejected) ===")
print(f"  clean intra-stack drift per level: {[round(v,2) for v in drift]} %")
print(f"  read/dark var ~ {read_var:.0f} counts^2 ({np.sqrt(read_var):.1f} counts)")
print(f"  measured gain = {gain:.2f} e-/count  vs firmware CG 1.36  | full well ~ {65520*gain:,.0f} e-")
print(f"  (valid only if drift << shot noise; flicker/clouds inflate var -> gain biased LOW)")

# plot: daylight spectra + NIR zoom
fig = Figure(figsize=(9, 3.8), dpi=120); fig.patch.set_facecolor("white")
ax = fig.add_subplot(121)
for p in sorted(clean):
    ax.plot(nm, clean[p], lw=1.2, label=f"{p}%")
ax.set_title("Daylight vs shutter opening (meas ch)", color="#01386a")
ax.set_xlabel("wavelength (nm)"); ax.set_ylabel("counts - dark"); ax.grid(alpha=0.15); ax.legend(fontsize=7)
ax2 = fig.add_subplot(122)
ax2.plot(nm, fb, color="#c1121f", lw=1.3)
ax2.axvspan(759, 762, color="#888", alpha=0.2); ax2.set_xlim(650, 851)
ax2.set_title(f"NIR detail ({best}% open) - O2 A-band marked", color="#01386a")
ax2.set_xlabel("wavelength (nm)"); ax2.grid(alpha=0.15)
fig.tight_layout()
out = os.path.join(HERE, "output", "shutter_char.png")
FigureCanvasAgg(fig).print_png(out)
print("\nplot:", out)
