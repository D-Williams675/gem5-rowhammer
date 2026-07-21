#!/usr/bin/env python3
# Plot the REAL gem5 sweep results (per-category bit flips over 300 attacks)
# and a side-by-side comparison with the analytical model prediction.
import csv, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

csv_path, out_gem5, out_cmp = sys.argv[1], sys.argv[2], sys.argv[3]
CATS = ["X", "Y", "Z", "P"]
MEAN = {"X": "very weak", "Y": "weak", "Z": "strong", "P": "very strong"}

rows = list(csv.DictReader(open(csv_path)))
data = {c: np.array([float(r[c]) for r in rows]) for c in CATS}
totals = np.array([float(r["total_flips"]) for r in rows])
n = len(rows)
mean_all = {c: data[c].mean() for c in CATS}      # mean over ALL attacks
sum_all = {c: int(data[c].sum()) for c in CATS}    # total flips per category

# ---- Graph 1: real gem5, flips per category over all attacks ----------
x = np.arange(len(CATS))
fig, ax = plt.subplots(figsize=(8, 5.5))
rng = np.random.default_rng(0)
for i, c in enumerate(CATS):
    j = rng.uniform(-0.12, 0.12, size=n)
    ax.scatter(x[i] + j, data[c], s=12, alpha=0.25, color="#4C78A8",
               edgecolors="none", zorder=2,
               label="individual attacks" if i == 0 else None)
means = [mean_all[c] for c in CATS]
ax.plot(x, means, "o-", color="#E45756", lw=2.2, ms=8, zorder=4,
        label="mean flips per attack (trend)")
for i, c in enumerate(CATS):
    ax.annotate("%.1f" % mean_all[c], (x[i], mean_all[c]),
                textcoords="offset points", xytext=(10, 8),
                fontsize=10, color="#E45756", fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(["%s\n(%s)" % (c, MEAN[c]) for c in CATS])
ax.set_xlabel("cell vulnerability category (most -> least vulnerable)")
ax.set_ylabel("bit flips per attack")
ax.set_title("REAL gem5 simulation: bit flips by cell category\n"
             "(synthetic model, %d attacks, row 791 double-sided)" % n)
ax.grid(True, axis="y", alpha=0.3); ax.legend(loc="upper right")
ax.set_ylim(bottom=0); fig.tight_layout(); fig.savefig(out_gem5, dpi=150)
print("wrote", out_gem5)

# ---- Graph 2: model vs gem5, normalized shares (share of all flips) ----
# Absolute scales differ (model = one fully-weak row, all 1024 cells tested
# once; gem5 = one attack sampling columns over a limited window), so compare
# the *shape*: each category's share of the total flips.
model_flips = {"X": 387, "Y": 107, "Z": 31, "P": 16}
mtot = sum(model_flips.values())
gtot = sum(sum_all.values())
model_share = [model_flips[c] / mtot * 100 for c in CATS]
gem5_share = [sum_all[c] / gtot * 100 for c in CATS]

fig2, ax2 = plt.subplots(figsize=(8, 5.5))
w = 0.38
ax2.bar(x - w/2, model_share, w, label="analytical model", color="#72B7B2")
ax2.bar(x + w/2, gem5_share, w, label="real gem5 (300 attacks)",
        color="#E45756")
for i in range(len(CATS)):
    ax2.annotate("%.0f%%" % model_share[i], (x[i]-w/2, model_share[i]),
                 textcoords="offset points", xytext=(0, 3), ha="center",
                 fontsize=9)
    ax2.annotate("%.0f%%" % gem5_share[i], (x[i]+w/2, gem5_share[i]),
                 textcoords="offset points", xytext=(0, 3), ha="center",
                 fontsize=9)
ax2.set_xticks(x); ax2.set_xticklabels(["%s\n(%s)" % (c, MEAN[c]) for c in CATS])
ax2.set_xlabel("cell vulnerability category (most -> least vulnerable)")
ax2.set_ylabel("share of all bit flips (%)")
ax2.set_title("Shape check: model vs. gem5\n"
              "each category's share of total flips (downward trend)")
ax2.grid(True, axis="y", alpha=0.3); ax2.legend()
fig2.tight_layout(); fig2.savefig(out_cmp, dpi=150)
print("wrote", out_cmp)

# ---- text summary -----------------------------------------------------
print("\ngem5 sweep: %d attacks, total flips summed = %d" % (n, gtot))
print("median total flips/attack = %.0f, mean = %.1f, max = %.0f"
      % (np.median(totals), totals.mean(), totals.max()))
frac_nonzero = np.count_nonzero(totals) / n * 100
print("attacks with >=1 flip: %.0f%% (row 791 classified weak ~30%% of seeds)"
      % frac_nonzero)
print("\n%-4s %-12s %8s %10s %12s %12s" %
      ("cat", "meaning", "gem5 sum", "gem5 mean", "gem5 share", "model share"))
for i, c in enumerate(CATS):
    print("%-4s %-12s %8d %10.2f %11.0f%% %11.0f%%" %
          (c, MEAN[c], sum_all[c], mean_all[c], gem5_share[i], model_share[i]))
