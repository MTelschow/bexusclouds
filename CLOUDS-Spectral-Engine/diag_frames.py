"""Diagnose the frame-to-frame variance artifact in power_estimate.npz."""
import numpy as np

d = np.load("output/power_estimate.npz", allow_pickle=True)
L, D, exps, good = d["light_frames"], d["dark_frames"], d["exposures_us"], d["good"]
print("light", L.shape, "dark", D.shape, "exps_ms", (exps / 1000).round(1))

d0 = D[0]                                   # (M,2048) dark, shortest exposure
gm = d0.mean(axis=1)
print(f"\nDARK L0 per-frame global mean (first 10): {gm[:10].round(1)}")
print(f"  global-mean std across frames = {gm.std():.2f} counts "
      f"({100*gm.std()/gm.mean():.2f}% global flicker)")

pstd = d0.std(0, ddof=1)
print(f"\nDARK L0 pixel temporal std: median={np.median(pstd):.0f}  "
      f"frac>1000={100*(pstd>1000).mean():.0f}%  n(<100)={int((pstd<100).sum())}")

print("\n5 highest-variance dark pixels (values across first 8 frames):")
for p in np.argsort(pstd)[-5:]:
    print(f"  pix{p:4d} std={pstd[p]:6.0f}: {d0[:8, p].astype(int)}")
print("5 stable dark pixels:")
for p in np.where(pstd < 60)[0][:5]:
    print(f"  pix{p:4d} std={pstd[p]:6.1f}: {d0[:8, p].astype(int)}")

# does the comb move frame-to-frame?
hi0 = set(np.where(d0[0] > 20000)[0].tolist())
hi1 = set(np.where(d0[1] > 20000)[0].tolist())
print(f"\ncomb pixels(>20000): frame0 n={len(hi0)}  frame1 n={len(hi1)}  "
      f"shared={len(hi0 & hi1)}  moved={len(hi0 ^ hi1)}")
print("  frame0 comb idx:", sorted(hi0)[:14])
print("  frame1 comb idx:", sorted(hi1)[:14])

# light frame sanity: is the MEAN well-behaved & is light variance also artifact-driven?
l_hi = L[-1]                                 # brightest exposure
lm = l_hi.mean(0)
lstd = l_hi.std(0, ddof=1)
sel = good & (lm > 15000) & (lm < 50000)
print(f"\nLIGHT top-exp: lit pixels {int(sel.sum())}; on those: "
      f"mean~{np.median(lm[sel]):.0f}  temporal-std median~{np.median(lstd[sel]):.0f} "
      f"(shot-only would be ~{np.sqrt(np.median(lm[sel])):.0f} at g=1)")
gm_l = l_hi.mean(1)
print(f"  light per-frame global mean std = {100*gm_l.std()/gm_l.mean():.2f}% (source+readout flicker)")
