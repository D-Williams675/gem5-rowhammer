#!/usr/bin/env python3
# Copyright (c) 2025 The Regents of the University of California
# All rights reserved.
#
# Blast-radius analysis: bit flips vs. aggressor-to-victim row distance.
#
# Reads the RowHammer traces produced by a blast-radius sweep (every flip
# line carries a "distance <d>" field) and reports the per-distance profile,
# then compares it against the BlockHammer blast impact factor
# c_k = 0.5^(k-1) (Yaglikci et al., HPCA 2021, Sec. 6).
#
# IMPORTANT -- normalization. Raw flip totals are NOT comparable across
# distances, because the number of (aggressor, victim) pairs differs. With
# the standard 2-aggressor double-sided config (aggressors at r-1 and r+1),
# distance 1 collapses onto the single sandwiched victim row fed by BOTH
# aggressors, while each larger distance reaches four distinct rows fed by
# one aggressor each. Comparing raw totals makes the profile look
# inconsistent with c_k; dividing by the pair count shows it matches.
#
# Pair counts are computed geometrically from the aggressor rows supplied
# via --aggressors, intersected with the victim rows that actually received
# flips (so attack-type gating at distance 1 is accounted for). Without
# --aggressors only raw counts are reported, with a warning.
#
# Example:
#   util/hammersim/plot_blast_radius.py --traces <sweep_dir> \
#       --aggressors 790,792 --out blast_radius.png

import argparse
import collections
import glob
import os
import re

FLIP_RE = re.compile(r"row (\d+) col (\d+).*distance (-?\d+)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--traces", required=True,
                    help="Directory containing *.trace files from the sweep.")
    ap.add_argument("--out", default="blast_radius.png",
                    help="Output plot path (omit to skip plotting).")
    ap.add_argument("--csv", default=None, help="Optional CSV output.")
    ap.add_argument("--no-plot", action="store_true",
                    help="Report numbers only; do not render a plot.")
    ap.add_argument("--aggressors", default=None,
                    help="Comma-separated aggressor row numbers, e.g. "
                         "'790,792'. Required for the per-pair "
                         "normalization; without it only raw counts are "
                         "reported (which are NOT comparable across "
                         "distances -- see the note at the top of this "
                         "file).")
    args = ap.parse_args()
    aggressors = ([int(a) for a in args.aggressors.split(",")]
                  if args.aggressors else None)

    signed = collections.Counter()          # signed distance -> flips
    by_dist = collections.Counter()         # |distance|      -> flips
    victims = collections.defaultdict(set)  # |distance|      -> victim rows

    files = sorted(glob.glob(os.path.join(args.traces, "*.trace")))
    if not files:
        ap.error("no .trace files found in %s" % args.traces)
    for f in files:
        for line in open(f):
            m = FLIP_RE.search(line)
            if not m:
                continue
            row, d = int(m.group(1)), int(m.group(3))
            signed[d] += 1
            by_dist[abs(d)] += 1
            victims[abs(d)].add(row)

    if not by_dist:
        print("No distance-tagged flips found. Was the sweep run with a "
              "blast-radius-enabled build and --blast-radius >= 2?")
        return

    ck = {k: 0.5 ** (k - 1) for k in sorted(by_dist)}
    print("Blast-radius profile from %d trace files\n" % len(files))

    if aggressors is None:
        print("dist | flips | victim rows")
        print("-" * 30)
        for d in sorted(by_dist):
            print("  %d  | %5d |     %2d" % (d, by_dist[d], len(victims[d])))
        print("-" * 30)
        print("\nNOTE: raw totals are NOT comparable across distances -- the\n"
              "number of (aggressor, victim) pairs differs. Pass "
              "--aggressors\nto get the normalized comparison against "
              "BlockHammer's c_k.")
        print("\nsigned distances: %s"
              % {k: signed[k] for k in sorted(signed)})
        return

    # Pair count per distance, derived geometrically: every (aggressor,
    # victim) relationship where victim = aggressor +/- d, restricted to
    # victim rows that actually received flips. The restriction matters
    # because checkRowHammer gates distance-1 victims by attack type, so
    # a double-sided attack leaves the outer distance-1 neighbours clean;
    # counting them would understate the per-pair rate at distance 1.
    pair_count = {}
    for d in sorted(by_dist):
        n = 0
        for a in aggressors:
            for v in (a - d, a + d):
                if v in victims[d]:
                    n += 1
        pair_count[d] = max(1, n)

    dmin = min(by_dist)
    base = by_dist[dmin] / pair_count[dmin]

    print("aggressor rows: %s" % aggressors)
    print("dist | flips | victim rows | pairs | flips/pair | rel. | c_k")
    print("-" * 62)
    for d in sorted(by_dist):
        per = by_dist[d] / pair_count[d]
        print("  %d  | %5d |     %2d      |   %d   |  %8.1f  |%5.3f |%6.4f"
              % (d, by_dist[d], len(victims[d]), pair_count[d], per,
                 per / base, ck[d]))
    print("-" * 62)
    dev = max(abs(by_dist[d] / pair_count[d] / base - ck[d])
              for d in by_dist)
    print("max deviation from c_k after normalization: %.4f" % dev)
    print("\nsigned distances: %s"
          % {k: signed[k] for k in sorted(signed)})

    if args.csv:
        import csv as _csv
        with open(args.csv, "w", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["distance", "flips", "victim_rows", "pairs",
                        "flips_per_pair", "relative", "blockhammer_ck"])
            for d in sorted(by_dist):
                per = by_dist[d] / pair_count[d]
                w.writerow([d, by_dist[d], len(victims[d]), pair_count[d],
                            round(per, 2), round(per / base, 4),
                            round(ck[d], 5)])
        print("wrote %s" % args.csv)

    if args.no_plot:
        return

    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ds = sorted(by_dist)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.4))

    xs = sorted(signed)
    ax1.bar(range(len(xs)), [signed[d] for d in xs],
            color=["#8FA8C8" if d < 0 else "#4C78A8" for d in xs],
            edgecolor="white", width=0.72)
    for i, d in enumerate(xs):
        ax1.annotate(str(signed[d]), (i, signed[d]),
                     textcoords="offset points", xytext=(0, 3),
                     ha="center", fontsize=8.5, fontweight="bold")
    ax1.set_xticks(range(len(xs)))
    ax1.set_xticklabels(["%+d" % d for d in xs], fontsize=9)
    ax1.set_xlabel("victim row offset from aggressor row")
    ax1.set_ylabel("bit flips")
    ax1.set_title("A. Flips by signed distance")
    ax1.grid(True, axis="y", alpha=0.3)
    ax1.spines[["top", "right"]].set_visible(False)

    x = np.arange(len(ds))
    w = 0.38
    obs_n = [by_dist[d] / pair_count[d] / base for d in ds]
    ax2.bar(x - w / 2, obs_n, w, label="gem5 (per aggressor-victim pair)",
            color="#C0392B", edgecolor="white")
    ax2.bar(x + w / 2, [ck[d] for d in ds], w,
            label="BlockHammer $c_k=0.5^{k-1}$", color="#72B7B2",
            edgecolor="white")
    ax2.set_xticks(x)
    ax2.set_xticklabels(["+/-%d" % d for d in ds])
    ax2.set_xlabel("|distance| from aggressor row")
    ax2.set_ylabel("flips relative to nearest distance")
    ax2.set_title("B. Normalized decay vs. BlockHammer $c_k$")
    ax2.grid(True, axis="y", alpha=0.3)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.legend(fontsize=9)

    fig.suptitle("RowHammer blast radius (gem5)", fontsize=13,
                 fontweight="bold")
    fig.tight_layout(rect=[0, 0.02, 1, 0.93])
    fig.savefig(args.out, dpi=150)
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
