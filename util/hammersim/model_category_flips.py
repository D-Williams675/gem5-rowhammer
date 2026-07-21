#!/usr/bin/env python3
# Copyright (c) 2025 The Regents of the University of California
# All rights reserved.
#
# Analytical + Monte-Carlo view of the synthetic weak-cell RowHammer model.
#
# A "weak" DRAM row has N cells. The model (see src/mem/DRAMInterface.py and
# dram_interface.cc: sampleBucketedProbability / getCellFlipProbability)
# splits those cells into four vulnerability categories by weight, and gives
# each cell a per-cell flip probability drawn uniformly from its category's
# probability range:
#
#   Category  Meaning       weight   prob range      avg prob
#   --------  ------------  -------  --------------  --------
#   X         very weak      42 %    [0.80, 1.00)     0.90
#   Y         weak           16 %    [0.50, 0.80)     0.65
#   Z         strong         10 %    [0.10, 0.50)     0.30
#   P         very strong    32 %    [0.00, 0.10)     0.05
#
# The category weights sum to 100 %, so (#X + #Y + #Z + #P) == N by
# construction. During an attack, each cell flips with its own probability;
# the expected number of flips in a category is (#cells * avg prob), which
# decreases from X to P even though X and P hold the most cells -- the
# probability term dominates, producing a downward trend.
#
# This script runs many simulated attacks (each a fresh random draw of the
# category assignment, per-cell probabilities, and flip outcomes, exactly as
# different gem5 --seed values would), then reports a table and a plot of the
# per-category flip counts with the downward mean trend line.

import argparse

import numpy as np

# Ordered most-vulnerable -> least-vulnerable (this is the x-axis order and
# the direction of the downward trend).
CATEGORIES = ["X", "Y", "Z", "P"]
MEANINGS = {"X": "very weak", "Y": "weak", "Z": "strong", "P": "very strong"}
# (weight fraction, prob_low, prob_high) -- matches DRAMInterface.py defaults.
MODEL = {
    "X": (0.42, 0.80, 1.00),
    "Y": (0.16, 0.50, 0.80),
    "Z": (0.10, 0.10, 0.50),
    "P": (0.32, 0.00, 0.10),
}


def run(n_cells, n_attacks, seed):
    rng = np.random.default_rng(seed)
    weights = np.array([MODEL[c][0] for c in CATEGORIES])
    lows = np.array([MODEL[c][1] for c in CATEGORIES])
    highs = np.array([MODEL[c][2] for c in CATEGORIES])

    flips = np.zeros((n_attacks, len(CATEGORIES)), dtype=int)
    cells = np.zeros((n_attacks, len(CATEGORIES)), dtype=int)

    for a in range(n_attacks):
        # Assign each of N cells to a category (multinomial by weight), just
        # as a fresh weak row would be classified under a new seed.
        counts = rng.multinomial(n_cells, weights)
        cells[a] = counts
        for ci in range(len(CATEGORIES)):
            k = counts[ci]
            if k == 0:
                continue
            # Each cell's fixed flip probability, uniform within its bucket.
            probs = rng.uniform(lows[ci], highs[ci], size=k)
            # One hammering pass: each cell flips with its own probability.
            flips[a, ci] = int(np.count_nonzero(rng.random(k) < probs))
    return cells, flips


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cells", type=int, default=1024,
                    help="Cells per weak row, N (default: 1024).")
    ap.add_argument("--attacks", type=int, default=300,
                    help="Number of simulated attacks (default: 300).")
    ap.add_argument("--seed", type=int, default=1, help="RNG seed.")
    ap.add_argument("--out", default="category_flips.png",
                    help="Output plot path (default: category_flips.png).")
    ap.add_argument("--csv", default=None,
                    help="Optional path to write per-attack flip counts.")
    args = ap.parse_args()

    cells, flips = run(args.cells, args.attacks, args.seed)
    mean_cells = cells.mean(axis=0)
    mean_flips = flips.mean(axis=0)
    std_flips = flips.std(axis=0)
    avg_prob = np.array([(MODEL[c][1] + MODEL[c][2]) / 2 for c in CATEGORIES])
    expected = mean_cells * avg_prob

    # ---- Table -------------------------------------------------------
    print("\nSynthetic weak-cell RowHammer model: %d cells/row, %d attacks\n"
          % (args.cells, args.attacks))
    hdr = ("cat", "meaning", "weight", "prob range", "avg p",
           "~cells", "exp flips", "mean flips", "std")
    print("%-3s %-12s %7s %-13s %6s %7s %9s %10s %6s" % hdr)
    print("-" * 82)
    for i, c in enumerate(CATEGORIES):
        w, lo, hi = MODEL[c]
        print("%-3s %-12s %6.0f%% [%.2f, %.2f) %6.2f %7.0f %9.0f %10.1f %6.1f"
              % (c, MEANINGS[c], w * 100, lo, hi, avg_prob[i],
                 mean_cells[i], expected[i], mean_flips[i], std_flips[i]))
    print("-" * 82)
    print("%-3s %-12s %6.0f%% %13s %6s %7.0f %9.0f %10.1f"
          % ("all", "", 100, "", "", mean_cells.sum(), expected.sum(),
             mean_flips.sum()))
    print()

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["attack"] + CATEGORIES + ["total"])
            for a in range(args.attacks):
                w.writerow([a] + list(flips[a]) + [int(flips[a].sum())])
        print("Wrote per-attack CSV: %s" % args.csv)

    # ---- Plot --------------------------------------------------------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.arange(len(CATEGORIES))
    fig, ax = plt.subplots(figsize=(8, 5.5))

    # Per-attack scatter (jittered) so all hundreds of attacks are visible.
    rng = np.random.default_rng(0)
    for i in range(len(CATEGORIES)):
        jitter = rng.uniform(-0.12, 0.12, size=args.attacks)
        ax.scatter(x[i] + jitter, flips[:, i], s=10, alpha=0.25,
                   color="#4C78A8", edgecolors="none",
                   label="individual attacks" if i == 0 else None, zorder=2)

    # Downward mean trend line with std error bars.
    ax.errorbar(x, mean_flips, yerr=std_flips, fmt="o-", color="#E45756",
                lw=2.2, ms=8, capsize=5, zorder=4,
                label="mean flips (trend)")

    # Annotate each mean.
    for i in range(len(CATEGORIES)):
        ax.annotate("%.0f" % mean_flips[i], (x[i], mean_flips[i]),
                    textcoords="offset points", xytext=(10, 8),
                    fontsize=10, color="#E45756", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(["%s\n(%s)" % (c, MEANINGS[c]) for c in CATEGORIES])
    ax.set_xlabel("cell vulnerability category "
                  "(most -> least vulnerable)", fontsize=11)
    ax.set_ylabel("number of bit flips per attack", fontsize=11)
    ax.set_title("RowHammer bit flips by cell category over %d attacks\n"
                 "(N = %d cells per weak row)"
                 % (args.attacks, args.cells), fontsize=12)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper right", framealpha=0.9)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print("Wrote plot: %s" % args.out)


if __name__ == "__main__":
    main()
