"""Final optical-power figures for the EURECA Duo, from measured + firmware constants.

Constants (this unit, TCD1304DG):
  gain  g = 1.36 e-/count            (firmware CG1.36; full well = 65520*g = 89 ke-)
  read+dark noise = 28 e- (measured, clean) ... 46 e- (firmware RN46.1)
  dispersion ~ 2.6 nm/pixel; one spectral channel ~ 235 px
We report the optical power needed for a usable spectrum (per-pixel SNR target) and,
for context, the power that SATURATES a pixel -- both referred to the fibre input.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

HERE = os.path.dirname(os.path.abspath(__file__))
HCJ = 6.62607015e-34 * 299792458.0
G = 1.36                      # e-/count (firmware)
FULL_WELL = 65520 * G         # e-
N_CH = 235                    # pixels in one spectral channel


def Eph(nm):
    return HCJ / (nm * 1e-9)


def min_detect(snr, read_e, qe, thru, t, npx, nm=660.0, dc_e_s=1300.0):
    noise = np.sqrt(read_e**2 + dc_e_s * t)
    S = (snr**2 + np.sqrt(snr**4 + 4 * snr**2 * noise**2)) / 2.0    # e-/px
    p_pix_det = (S / qe) * Eph(nm) / t                              # W on one pixel
    return p_pix_det, p_pix_det * npx, p_pix_det * npx / thru       # pix-det, band-det, band-fibre


def sat_input(t, qe, thru, nm=660.0):
    rate = FULL_WELL / t                                           # e-/s to fill well in t
    return ((rate / qe) * Eph(nm)) / thru                          # W/pixel at fibre


print("=" * 70)
print("MINIMUM DETECTABLE OPTICAL POWER (per-pixel SNR=10), red ~660 nm")
print("=" * 70)
print(f"{'t':>6} {'QE':>5} {'thru':>5} {'read':>5} | {'pW/px@det':>10} "
      f"{'pW/px@fibre':>12} {'nW band@fibre':>14}")
for t in (0.1, 1.0):
    for qe in (0.30,):
        for thru in (0.05, 0.10, 0.20):
            for read_e in (28.0,):
                pp, pb, pf = min_detect(10, read_e, qe, thru, t, N_CH)
                print(f"{t*1000:5.0f}m {qe:5.2f} {thru:5.2f} {read_e:5.0f} | "
                      f"{pp*1e12/ (1):10.4f} {pp/thru*1e12:12.4f} {pf*1e9:14.4f}")

print("\nNOMINAL (QE 0.30, throughput 0.10, read 28 e-, 100 ms, 235 px, 660 nm):")
pp, pb, pf = min_detect(10, 28, 0.30, 0.10, 0.1, N_CH)
print(f"  per pixel @ detector  = {pp*1e15:7.1f} fW")
print(f"  per pixel @ fibre-in  = {pp/0.10*1e15:7.1f} fW = {pp/0.10*1e12:.4f} pW")
print(f"  full spectrum @ fibre = {pf*1e12:7.2f} pW = {pf*1e9:.4f} nW")
print(f"  vs LCU ~2.5 mW peak   -> ~{2.5e-3/pf:,.0f}x more light than the floor")

print("\nSATURATION (fills the 89 ke- well), red 660 nm, QE 0.30, throughput 0.10:")
for t in (0.001, 0.01, 0.1):
    s = sat_input(t, 0.30, 0.10)
    print(f"  at {t*1000:6.1f} ms integration: ~{s*1e9:8.2f} nW/pixel at the fibre "
          f"(~{s*N_CH*1e9:7.1f} nW across the band)")

# ---- spectrum + linearity figure from the saved frames ----
d = np.load(os.path.join(HERE, "output", "power_estimate.npz"), allow_pickle=True)
L, D = d["light_frames"], d["dark_frames"]
exps = d["exposures_us"].astype(float)
wl = d["wavelengths"]; win = d["ch_window"].astype(int)
medL = np.median(L[-1], axis=0)         # corruption-robust
medD = np.median(D[-1], axis=0)
sig_ch = (medL - medD)[win]
peakpix = win[int(np.argmax(sig_ch))]
sig_vs_exp = np.array([np.median(L[i], axis=0)[peakpix] - np.median(D[i], axis=0)[peakpix]
                       for i in range(len(exps))])

fig = Figure(figsize=(9, 3.8), dpi=120); fig.patch.set_facecolor("white")
ax1 = fig.add_subplot(121)
ax1.plot(wl, sig_ch, color="#01386a", lw=1.4)
ax1.set_title("Clean spectrum thru red caps (floor lamp 1)", color="#01386a")
ax1.set_xlabel("wavelength (nm)"); ax1.set_ylabel("counts (light - dark)"); ax1.grid(alpha=0.15)
ax2 = fig.add_subplot(122)
ax2.plot(exps / 1000, sig_vs_exp * G, "o-", color="#c1121f", lw=1.4, ms=4)
ax2.set_title(f"Linearity at peak px {peakpix}", color="#01386a")
ax2.set_xlabel("integration (ms)"); ax2.set_ylabel("electrons"); ax2.grid(alpha=0.15)
fig.tight_layout()
out = os.path.join(HERE, "output", "power_summary.png")
FigureCanvasAgg(fig).print_png(out)
print("\nplot:", out)
print(f"peak wavelength ~ {wl[int(np.argmax(sig_ch))]:.0f} nm (red, as expected through the caps)")
