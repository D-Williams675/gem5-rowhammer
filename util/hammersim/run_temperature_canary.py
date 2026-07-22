#!/usr/bin/env python3
# Copyright (c) 2025 The Regents of the University of California
# All rights reserved.
#
# Temperature-dependent weak-cell (W0 + canary) experiment driver.
#
# Runs the temperature RowHammer config over a set of seeds and a set of
# temperatures, then classifies every cell that ever flips by HOW MANY
# temperatures it flips at:
#   - a cell that flips at ALL tested temperatures  -> W0 (always weak)
#   - a cell that flips at exactly ONE temperature  -> canary (temperature
#     specific), the behavior from Orosa et al. "SpyHammer" (2022), Fig. 4.
#
# For a given seed the simulated chip is fixed (same W0 / canary assignment),
# so comparing which cells flip across temperatures reveals the structure.
#
# Example:
#   util/hammersim/run_temperature_canary.py \
#       --gem5 build/X86/gem5.opt \
#       --config configs/dram/rowhammer/TrafficGen/vendor-B/within_rows/\
# dimm1/row791_temperature.py \
#       --seeds 60 --temps 50,60,70,80,90 --out temp_canary.csv

import argparse
import csv
import os
import re
import subprocess
import tempfile
from collections import defaultdict

BITFLIP_RE = re.compile(r"Bitflip at bank (\d+) row (\d+) col (\d+)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gem5", default="build/X86/gem5.opt")
    ap.add_argument("--config", required=True)
    ap.add_argument("--seeds", type=int, default=60,
                    help="Number of seeds, 1..N (default 60).")
    ap.add_argument("--temps", default="50,60,70,80,90",
                    help="Comma-separated temperatures in C.")
    ap.add_argument("--out", default="temp_canary.csv",
                    help="CSV of canary-cells-per-temperature + summary.")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    temps = [int(t) for t in args.temps.split(",")]
    seeds = list(range(1, args.seeds + 1))
    workdir = args.workdir or tempfile.mkdtemp(prefix="temp_canary_")
    os.makedirs(workdir, exist_ok=True)

    # (seed,row,col) -> set of temperatures at which it flipped
    cell_temps = defaultdict(set)
    for s in seeds:
        for t in temps:
            trace = os.path.join(workdir, "s%d_t%d.trace" % (s, t))
            outdir = os.path.join(workdir, "o")
            subprocess.run(
                [args.gem5, "--outdir=%s" % outdir, args.config,
                 "--seed", str(s), "--temperature", str(t),
                 "--trace-file", trace],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not os.path.exists(trace):
                continue
            with open(trace) as fh:
                for line in fh:
                    m = BITFLIP_RE.search(line)
                    if m:
                        cell_temps[(s, int(m.group(2)), int(m.group(3)))].add(t)
        print("seed %d/%d done" % (s, len(seeds)))

    by_count = defaultdict(int)
    canary_per_temp = defaultdict(int)
    for temps_hit in cell_temps.values():
        by_count[len(temps_hit)] += 1
        if len(temps_hit) == 1:
            canary_per_temp[next(iter(temps_hit))] += 1
    w0 = by_count[len(temps)]
    canary = by_count[1]
    total = len(cell_temps)

    print("\n--- Temperature-dependent weak-cell classification ---")
    print("distinct flipping cells: %d" % total)
    print("W0-like (flip at all %d temps): %d" % (len(temps), w0))
    print("canary-like (flip at exactly 1 temp): %d" % canary)
    for n in range(1, len(temps) + 1):
        print("  flip at %d/%d temps: %d cells" % (n, len(temps), by_count[n]))
    print("canary cells per temperature:")
    for t in temps:
        print("  %d C: %d" % (t, canary_per_temp[t]))

    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["temperature_C", "canary_cells"])
        for t in temps:
            w.writerow([t, canary_per_temp[t]])
        w.writerow([])
        w.writerow(["n_temps_flipped", "n_cells"])
        for n in range(1, len(temps) + 1):
            w.writerow([n, by_count[n]])
        w.writerow([])
        w.writerow(["W0_cells", w0])
        w.writerow(["canary_cells_total", canary])
        w.writerow(["distinct_flipping_cells", total])
    print("\nWrote %s" % args.out)


if __name__ == "__main__":
    main()
