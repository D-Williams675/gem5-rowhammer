#!/usr/bin/env python3
"""HammerSim property / invariant test harness.

Each check asserts one of the invariants in VERIFICATION.md by running the
built gem5 binary and comparing deterministic RowHammer traces and stat
counters (never host-timing fields). Exit status is non-zero if any invariant
fails, so this is usable directly as a CI gate.

Usage: run_properties.py [path/to/gem5.opt]   (default build/X86/gem5.opt)
Must be run from the repository root so configs resolve their device maps.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.getcwd()
GEM5 = sys.argv[1] if len(sys.argv) > 1 else "build/X86/gem5.opt"
ATTACK = "tests/hammersim/configs/rh_attack.py"
SMOKE = "configs/dram/rowhammer/TrafficGen/hammersim_smoke.py"

RH_STATS = [
    "rowHammerTotalBitflips",
    "rowHammerSingleSidedBitflips",
    "rowHammerDoubleSidedBitflips",
    "rowHammerHalfDoubleBitflips",
    "rowHammerCorruptedBitCount",
    "rowHammerEccCorrected",
    "rowHammerEccDetected",
]


class RunResult:
    def __init__(self, code, stats, trace):
        self.code = code
        self.stats = stats
        self.trace = trace


def run(config, config_args, outdir, gem5_args=None):
    os.makedirs(outdir, exist_ok=True)
    cmd = [GEM5, f"--outdir={outdir}"]
    cmd += gem5_args or []
    cmd += [config] + config_args
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    stats = {}
    stats_path = os.path.join(outdir, "stats.txt")
    if os.path.exists(stats_path):
        with open(stats_path) as handle:
            text = handle.read()
        for name in RH_STATS:
            match = re.search(rf"\b{name}\s+([0-9]+)", text)
            stats[name] = int(match.group(1)) if match else 0
    trace_path = os.path.join(outdir, "rowhammer.trace")
    trace = ""
    if os.path.exists(trace_path):
        with open(trace_path) as handle:
            trace = handle.read()
    return RunResult(proc.returncode, stats, trace)


RESULTS = []


def record(name, passed, detail):
    RESULTS.append((name, passed, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def flip_lines(trace):
    return [ln for ln in trace.splitlines() if ln.startswith("Bitflip at")]


def check_reproducibility(work):
    # I1: same config + same seed -> byte-identical trace and identical counters.
    base = ["--enable-rowhammer", "--enable-memory-corruption",
            "--enable-ecc", "--ecc-algorithm", "1", "--seed", "1"]
    a = run(ATTACK, base, os.path.join(work, "i1_a"))
    b = run(ATTACK, base, os.path.join(work, "i1_b"))
    ok = (a.code == 0 and b.code == 0 and a.trace == b.trace and
          a.stats == b.stats and len(flip_lines(a.trace)) > 0)
    record("I1 reproducibility", ok,
           f"exit={a.code}/{b.code} flips={len(flip_lines(a.trace))} "
           f"trace_identical={a.trace == b.trace} stats_identical={a.stats == b.stats}")


def check_optin_inert(work):
    # I2 (inertness form): RowHammer OFF -> runs clean, zero flips, deterministic.
    off = ["--rowhammer-threshold", "3"]  # note: no --enable-rowhammer
    a = run(ATTACK, off, os.path.join(work, "i2_a"))
    b = run(ATTACK, off, os.path.join(work, "i2_b"))
    ok = (a.code == 0 and b.code == 0 and
          a.stats.get("rowHammerTotalBitflips", 0) == 0 and
          len(flip_lines(a.trace)) == 0 and a.stats == b.stats)
    record("I2 opt-in inert", ok,
           f"exit={a.code}/{b.code} flips={a.stats.get('rowHammerTotalBitflips', 0)} "
           f"deterministic={a.stats == b.stats}")


def check_corruption_noperturb(work):
    # I3: toggling memory corruption must not change the flip set (same seed).
    model = run(ATTACK, ["--enable-rowhammer", "--seed", "1"],
                os.path.join(work, "i3_model"))
    corrupt = run(ATTACK, ["--enable-rowhammer", "--enable-memory-corruption",
                           "--seed", "1"], os.path.join(work, "i3_corrupt"))
    ok = (model.code == 0 and corrupt.code == 0 and
          model.trace == corrupt.trace and len(flip_lines(model.trace)) > 0)
    record("I3 corruption non-perturbation", ok,
           f"exit={model.code}/{corrupt.code} "
           f"flips={len(flip_lines(model.trace))} identical={model.trace == corrupt.trace}")


def check_edge_safety(work):
    # I4: hammering rows near either edge, under every targeted-refresh TRR
    # variant, must run to completion with no crash (and, under a sanitizer
    # build, no memory-safety report). The 16 MiB range gives 128 rows/bank,
    # so 126 is the top row that still has a victim above it.
    edge_rows = [0, 1, 2, 124, 126]
    variants = [0, 1, 2, 4, 6]
    failures = []
    for variant in variants:
        for row in edge_rows:
            r = run(ATTACK, ["--enable-rowhammer", "--trr-variant", str(variant),
                             "--aggressor-row", str(row), "--hammers", "8"],
                    os.path.join(work, f"i4_v{variant}_r{row}"))
            if r.code != 0:
                failures.append(f"v{variant}/row{row}=exit{r.code}")
    record("I4 edge safety", not failures,
           f"{len(variants) * len(edge_rows)} runs; "
           f"{'no crashes' if not failures else 'CRASHED: ' + ', '.join(failures)}")


def check_ecc_soundness(work):
    # I5: the deterministic smoke test must correct 4 single-bit and detect 1
    # multi-bit codeword (its orchestrated golden), i.e. ECC is active and no
    # corrupted-then-read word passes silently.
    r = run(SMOKE, [], os.path.join(work, "i5"))
    corrected = r.stats.get("rowHammerEccCorrected", 0)
    detected = r.stats.get("rowHammerEccDetected", 0)
    ok = (r.code == 0 and corrected == 4 and detected == 1)
    record("I5 ECC soundness", ok,
           f"exit={r.code} corrected={corrected} (want 4) detected={detected} (want 1)")


def check_conservation(work):
    # I7: corrupted bits <= reported flips, both positive; corruption flips one
    # bit per reported flip.
    r = run(ATTACK, ["--enable-rowhammer", "--enable-memory-corruption",
                     "--seed", "1"], os.path.join(work, "i7"))
    flips = r.stats.get("rowHammerTotalBitflips", 0)
    corrupted = r.stats.get("rowHammerCorruptedBitCount", 0)
    ok = (r.code == 0 and flips > 0 and 0 < corrupted <= flips)
    record("I7 conservation/bounds", ok,
           f"exit={r.code} flips={flips} corrupted_bits={corrupted} "
           f"(need 0<corrupted<=flips)")


def main():
    if not os.path.exists(GEM5):
        print(f"gem5 binary not found: {GEM5}", file=sys.stderr)
        return 2
    work = tempfile.mkdtemp(prefix="hammersim_props_")
    try:
        check_reproducibility(work)
        check_optin_inert(work)
        check_corruption_noperturb(work)
        check_edge_safety(work)
        check_ecc_soundness(work)
        check_conservation(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} invariants passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
