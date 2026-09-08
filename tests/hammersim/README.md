# HammerSim property-test harness

Layer 2 of [`VERIFICATION.md`](../../VERIFICATION.md): automated checks that the
HammerSim RowHammer model satisfies its invariants. Each check runs the built
gem5 binary and compares deterministic RowHammer traces and stat counters (never
host-timing fields), so it is usable directly as a CI gate.

## Run it

From the repository root, against a built binary:

```
python3 tests/hammersim/run_properties.py build/X86/gem5.opt
```

Exit status is non-zero if any invariant fails. The same command runs in CI both
against the normal `build-and-smoke-test` binary and, under Layer 1, against a
binary built with AddressSanitizer + UBSan.

## What it checks

| Check | Invariant (VERIFICATION.md) | How |
| --- | --- | --- |
| `check_reproducibility` | I1 reproducibility | same config + seed run twice → identical trace and RowHammer counters |
| `check_optin_inert` | I2 opt-in isolation | `enable_rowhammer` off → zero flips, deterministic |
| `check_corruption_noperturb` | I3 corruption non-perturbation | corruption off vs on at one seed → identical flip trace |
| `check_edge_safety` | I4 edge safety | hammer rows near both edges × TRR variants {0,1,2,4,6} → no crash (and, under sanitizers, no memory-safety report) |
| `check_ecc_soundness` | I5 ECC soundness | the deterministic smoke test corrects 4 single-bit and detects 1 multi-bit codeword |
| `check_conservation` | I7 conservation/bounds | corrupted bits > 0 and ≤ reported flips |

`configs/rh_attack.py` is a parameterized single-sided attack (all HammerSim
knobs on the command line) that the driver varies one dimension at a time.

## The tests have teeth

A check that can never fail is worthless. Verified against a codex-branch build:

- **All six invariants pass** (`6/6 invariants passed`).
- The trace comparison **discriminates**: hammering row 1 vs row 5 yields
  `Bitflip ... row 2` vs `Bitflip ... row 6`, and the harness reports them as
  different — so I1/I3's equality checks are not vacuous.
- **Seed control is real**: with a multi-weak-column map, `--seed 1/2/3` select
  different victim columns (8,11 / 15,5 / 9,10), and repeating a seed reproduces
  it byte-for-byte.
- Flips genuinely occur when RowHammer is enabled (so I2's "zero when off" is a
  real contrast), and ECC actually corrects/detects (so I5's exact counts bite).

## Not yet covered (future layers, see VERIFICATION.md)

- I6 monotonicity and I8 mitigation efficacy as standalone property checks (I8 is
  partially exercised by `hammersim_trr_smoke.py` today).
- L3 golden snapshots, L4 differential fuzzing, L5 coverage gate.
