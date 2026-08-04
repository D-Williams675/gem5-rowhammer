#!/usr/bin/env python3
# Copyright (c) 2025 The Regents of the University of California
# All rights reserved.
#
# Hardware aging analysis: RowHammer bit flips vs. the age of the part.
#
# Reads the traces from an aging sweep whose files are named
#   r<rate>_w<weeks>_s<seed>.trace
# and reports total bit flips per age, per aging rate, alongside the
# analytical prediction.
#
# Prediction. With a baseline weak fraction b (e.g. W0 + canary), only the
# currently non-weak cells are available to wear out, so
#
#     weak(t) = b + aging_rate * t * (1 - b)
#
# and flips scale with the weak fraction, giving a predicted relative
# increase of weak(t)/b - 1 over a brand-new part.
#
# Example:
#   util/hammersim/plot_aging.py --traces <sweep_dir> --baseline 0.32 \
#       --out aging.png --csv aging.csv

import argparse
import collections
import glob
import os
import re

NAME_RE = re.compile(r"r([0-9.eE+-]+)_w([0-9.]+)_s(\d+)\.trace$")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--traces", required=True,
                    help="Directory holding r<rate>_w<weeks>_s<seed>.trace")
    ap.add_argument("--baseline", type=float, default=0.32,
                    help="Baseline weak fraction at t=0 (default 0.32 = "
                         "w0_percent 30%% + 2%% canary).")
    ap.add_argument("--out", default="aging.png")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    # (rate, weeks) -> total flips ; and seed count for sanity
    totals = collections.Counter()
    seeds = collections.defaultdict(set)
    for f in glob.glob(os.path.join(args.traces, "*.trace")):
        m = NAME_RE.search(os.path.basename(f))
        if not m:
            continue
        rate, weeks, seed = float(m.group(1)), float(m.group(2)), m.group(3)
        n = sum(1 for line in open(f) if "Bitflip at" in line)
        totals[(rate, weeks)] += n
        seeds[(rate, weeks)].add(seed)

    if not totals:
        ap.error("no matching traces found in %s" % args.traces)

    rates = sorted({r for r, _ in totals})
    ages = sorted({w for _, w in totals})
    b = args.baseline

    rows = []
    print("Hardware aging sweep (%d seeds per point)\n"
          % len(next(iter(seeds.values()))))
    for r in rates:
        base = totals[(r, ages[0])]
        print("aging_rate = %g per week" % r)
        print("  weeks | years | flips | observed | predicted")
        for w in ages:
            n = totals[(r, w)]
            obs = n / base - 1.0
            pred = (b + r * w * (1 - b)) / b - 1.0
            print("  %5.0f | %5.1f | %5d | %+7.2f%% | %+7.2f%%"
                  % (w, w / 52.0, n, 100 * obs, 100 * pred))
            rows.append((r, w, n, obs, pred))
        print()

    if args.csv:
        import csv as _csv
        with open(args.csv, "w", newline="") as fh:
            wr = _csv.writer(fh)
            wr.writerow(["aging_rate", "age_weeks", "age_years", "flips",
                         "observed_increase", "predicted_increase"])
            for r, w, n, obs, pred in rows:
                wr.writerow([r, w, round(w / 52.0, 2), n,
                             round(obs, 5), round(pred, 5)])
        print("wrote %s" % args.csv)

    if args.no_plot:
        return

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.4))
    colors = {rates[0]: "#4C78A8"}
    if len(rates) > 1:
        colors[rates[-1]] = "#C0392B"

    for r in rates:
        ys = [totals[(r, w)] for w in ages]
        ax1.plot([w / 52.0 for w in ages], ys, "o-", lw=2, ms=7,
                 color=colors.get(r, "#888"),
                 label="aging_rate = %g / week" % r)
    ax1.set_xlabel("age of the DRAM part (years)")
    ax1.set_ylabel("total bit flips (100 attacks per point)")
    ax1.set_title("A. RowHammer bit flips increase as the part ages")
    ax1.grid(True, alpha=0.3)
    ax1.spines[["top", "right"]].set_visible(False)
    ax1.legend(fontsize=9)

    for r in rates:
        base = totals[(r, ages[0])]
        obs = [100 * (totals[(r, w)] / base - 1) for w in ages]
        pred = [100 * ((b + r * w * (1 - b)) / b - 1) for w in ages]
        ax2.plot([w / 52.0 for w in ages], obs, "o-", lw=2, ms=6,
                 color=colors.get(r, "#888"),
                 label="measured (rate %g)" % r)
        ax2.plot([w / 52.0 for w in ages], pred, "--", lw=1.6,
                 color=colors.get(r, "#888"), alpha=0.75,
                 label="predicted (rate %g)" % r)
    ax2.set_xlabel("age of the DRAM part (years)")
    ax2.set_ylabel("increase in bit flips vs. a new part (%)")
    ax2.set_title("B. Measured vs. analytical prediction")
    ax2.grid(True, alpha=0.3)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.legend(fontsize=8)

    fig.suptitle("Hardware aging in gem5:  weak set at time t = W0 + W(t), "
                 "|W(t)| = rate x t x bank cells",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0.02, 1, 0.93])
    fig.savefig(args.out, dpi=150)
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
