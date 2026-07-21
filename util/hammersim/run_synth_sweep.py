#!/usr/bin/env python3
# Copyright (c) 2025 The Regents of the University of California
# All rights reserved.
#
# RowHammer synthetic-model seed sweep driver.
#
# Runs the synthetic weak-row/weak-cell RowHammer model many times with
# different seeds, collecting per-run bit-flip counts into a CSV. When the
# simulator was built with per-flip bucket logging (the RhBucket debug
# flag), it also bins each run's flips by category (X / Y / Z / P).
#
# Example:
#   util/hammersim/run_synth_sweep.py \
#       --gem5 build/X86/gem5.opt \
#       --config configs/dram/rowhammer/TrafficGen/vendor-B/within_rows/\
# dimm1/row791_2_aggressor_rows_synth.py \
#       --num-seeds 300 --start-seed 1 --jobs 4 --out synth_sweep.csv
#
# The category boundaries match the model in DRAMInterface.py:
#   P (bucket1, "very strong"): prob in [0.00, 0.10)
#   Z (bucket2, "strong"):      prob in [0.10, 0.50)
#   Y (bucket3, "weak"):        prob in [0.50, 0.80)
#   X (bucket4, "very weak"):   prob in [0.80, 1.00]

import argparse
import concurrent.futures
import csv
import os
import re
import statistics
import subprocess
import sys
import tempfile

# Boundaries (upper bounds) for the weak-row buckets, must match the
# weak_bucket_p1..p4 defaults in DRAMInterface.py.
BUCKET_BOUNDS = [(0.10, "P"), (0.50, "Z"), (0.80, "Y"), (1.01, "X")]

# Matches the optional RhBucket debug line emitted by selectVictimColumn:
#   "Bucket flip bank 4 row 791 col 300 weak 1 prob 0.873421 bucket X"
BUCKET_RE = re.compile(
    r"Bucket flip .*prob (?P<prob>[0-9.]+) bucket (?P<bucket>[A-Z])")
# Matches the always-on per-flip trace line:
#   "Bitflip at bank 4 row 791 col 2885 single-sided 0"
BITFLIP_RE = re.compile(r"Bitflip at bank")


def categorize(prob):
    for bound, label in BUCKET_BOUNDS:
        if prob < bound:
            return label
    return "X"


def run_one(gem5, config, seed, workdir, extra_args):
    """Run a single seed; return (seed, total_flips, {bucket: count})."""
    outdir = os.path.join(workdir, "m5out_seed%d" % seed)
    trace = os.path.join(workdir, "rowhammer_seed%d.trace" % seed)
    debug = os.path.join(workdir, "debug_seed%d.log" % seed)
    cmd = [
        gem5,
        "--outdir=%s" % outdir,
        "--debug-flags=RhBucket",
        "--debug-file=trace.txt",
        config,
        "--seed", str(seed),
        "--trace-file", trace,
    ] + list(extra_args)

    with open(debug, "w") as dbg:
        proc = subprocess.run(cmd, stdout=dbg, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        sys.stderr.write(
            "seed %d: gem5 exited %d (see %s)\n"
            % (seed, proc.returncode, debug))
        return seed, None, {}

    # Total flips: count the always-on trace lines.
    total = 0
    if os.path.exists(trace):
        with open(trace) as fh:
            for line in fh:
                if BITFLIP_RE.search(line):
                    total += 1

    # Bucket breakdown (only present if built with RhBucket logging):
    buckets = {"X": 0, "Y": 0, "Z": 0, "P": 0}
    got_buckets = False
    tracetxt = os.path.join(outdir, "trace.txt")
    if os.path.exists(tracetxt):
        with open(tracetxt) as fh:
            for line in fh:
                m = BUCKET_RE.search(line)
                if m:
                    got_buckets = True
                    buckets[m.group("bucket")] = \
                        buckets.get(m.group("bucket"), 0) + 1
    return seed, total, (buckets if got_buckets else {})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gem5", default="build/X86/gem5.opt",
                    help="Path to the gem5 binary.")
    ap.add_argument("--config", required=True,
                    help="Path to the synthetic RowHammer config.")
    ap.add_argument("--num-seeds", type=int, default=300,
                    help="Number of seeds to run (default: 300).")
    ap.add_argument("--start-seed", type=int, default=1,
                    help="First seed value (default: 1).")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                    help="Parallel gem5 runs (default: #CPUs).")
    ap.add_argument("--out", default="synth_sweep.csv",
                    help="Output CSV path (default: synth_sweep.csv).")
    ap.add_argument("--workdir", default=None,
                    help="Directory for per-run outputs (default: a temp "
                         "dir that is kept for inspection).")
    ap.add_argument("extra", nargs=argparse.REMAINDER,
                    help="Extra args passed through to the config after '--'.")
    args = ap.parse_args()

    extra_args = args.extra
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    if not os.path.exists(args.gem5):
        ap.error("gem5 binary not found: %s" % args.gem5)

    workdir = args.workdir or tempfile.mkdtemp(prefix="rh_sweep_")
    os.makedirs(workdir, exist_ok=True)
    seeds = list(range(args.start_seed, args.start_seed + args.num_seeds))

    print("Running %d seeds (%d..%d) with %d parallel jobs; outputs in %s"
          % (len(seeds), seeds[0], seeds[-1], args.jobs, workdir))

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {
            ex.submit(run_one, args.gem5, args.config, s, workdir, extra_args): s
            for s in seeds
        }
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            seed, total, buckets = fut.result()
            results[seed] = (total, buckets)
            done += 1
            if done % 10 == 0 or done == len(seeds):
                print("  ... %d/%d runs complete" % (done, len(seeds)))

    have_buckets = any(b for (_, b) in results.values())
    fieldnames = ["seed", "total_flips"]
    if have_buckets:
        fieldnames += ["X", "Y", "Z", "P"]

    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for seed in seeds:
            total, buckets = results.get(seed, (None, {}))
            row = {"seed": seed, "total_flips": total}
            if have_buckets:
                for k in ("X", "Y", "Z", "P"):
                    row[k] = buckets.get(k, 0)
            w.writerow(row)

    totals = [t for (t, _) in results.values() if t is not None]
    print("\nWrote %s (%d successful runs)" % (args.out, len(totals)))
    if totals:
        print("total_flips: min=%d max=%d mean=%.1f median=%.1f stdev=%.1f"
              % (min(totals), max(totals), statistics.mean(totals),
                 statistics.median(totals),
                 statistics.pstdev(totals) if len(totals) > 1 else 0.0))
        distinct = sorted(set(totals))
        print("distinct total_flips values (%d): %s"
              % (len(distinct),
                 distinct if len(distinct) <= 20 else
                 "%s ... %s" % (distinct[:10], distinct[-5:])))
    if have_buckets:
        for k in ("X", "Y", "Z", "P"):
            vals = [b.get(k, 0) for (_, b) in results.values() if b]
            if vals:
                print("  bucket %s: mean=%.1f" % (k, statistics.mean(vals)))


if __name__ == "__main__":
    main()
