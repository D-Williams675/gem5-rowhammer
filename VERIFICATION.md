# HammerSim verification plan

Status: **plan of record (not yet implemented)**. This document is the agreed
design for how we guarantee the HammerSim RowHammer model in gem5 behaves as
intended. It describes the checks, the invariants they enforce, the files that
will hold them, and the order in which they land. No verification code has been
written yet; this document is reviewed and approved first.

## 1. Why this exists

HammerSim modifies the gem5 memory system in ways that are easy to get subtly
wrong: probabilistic fault injection, physical-address reconstruction, ECC
bookkeeping, and refresh-driven mitigation state. Two independent review passes
this cycle each found real defects the other had missed — out-of-bounds refresh
indexing, an ECC use-after-free, an ECC path that only ran on row-buffer misses,
a corruption RNG that perturbed the fault-selection stream, non-reproducible
seeding, and stock-gem5 behavior leaking into non-RowHammer runs. Manual review
and one-off runs are not a repeatable guarantee.

The goal is **defense in depth**: several independent, automated checks such
that a regression has to defeat *all* of them to reach a user. This does not
prove the absence of bugs — the vendor TRR mechanisms are proprietary
approximations and the ECC model is functional rather than timing-accurate — but
it makes "it still works as intended" a property that any change is measured
against automatically, by anyone, on every commit.

## 2. Scope

In scope: everything under the `enable_rowhammer` flag — fault selection
(`checkRowHammer`, `chooseWeakColumn`, `shouldFlip`), functional corruption and
address reconstruction (`doMemoryCorruption`, `dramAddress`), ECC
(`handleEccRead`, `handleWrite`, `eccVictims`), disturbance bookkeeping
(`updateVictims`, `resetVictimDisturbance`), and the mitigations (TRR variants
0/1/2/4/5/6 and PARA). Out of scope: the unmodified gem5 core, except the
guarantee that it stays unmodified when RowHammer is off (Invariant I2).

## 3. Invariants

These are the properties every change must preserve. Each is precise enough to
be asserted by a test. They are the heart of the system; the layers in §4 are
just the machinery that enforces them.

- **I1 Reproducibility.** For a fixed configuration and `--seed`, two runs
  produce byte-identical RowHammer traces and identical corrupted/ECC stat
  counters.
- **I2 Opt-in isolation.** With `enable_rowhammer=False`, the DRAM data path,
  timing, and stats are byte-identical to an unmodified gem5 of the same
  revision (compared against a stored stock golden).
- **I3 Corruption non-perturbation.** For a fixed seed, toggling
  `enable_memory_corruption` does not change which cells flip (the fault trace
  is identical). *(An initial version of this is already enforced in CI via the
  RNG-isolation trace diff.)*
- **I4 Edge safety.** Attacks on the lowest rows (0–4) and highest rows
  (`rowsPerBank-1 .. -5`), under every supported TRR variant, run to completion
  with no crash, no sanitizer report, and no reconstructed address outside the
  backing range.
- **I5 ECC soundness.** Every corrupted 64-bit word that is subsequently read is
  either corrected (exactly one differing bit, restored to the original) or
  detected (two or more differing bits, retained); no corrupted word is ever
  returned silently as clean. A write to a word clears its tracked state.
- **I6 Monotonicity.** Holding everything else fixed, increasing the number of
  hammer activations never decreases the number of induced flips; enabling a
  mitigation never increases them.
- **I7 Conservation / bounds.** Corrupted-bit count ≤ reported flip count ≤ the
  number of weak cells the device map declares for the targeted rows; every
  chosen column is `< rowBufferSize`; no cell is flipped twice without an
  intervening write.
- **I8 Mitigation efficacy.** Each supported TRR variant, run against an attack
  that flips without it, produces a nonzero inhibitor count, a well-formed trace
  record, and a strictly lower flip count; unsupported `trr_variant=3` is
  rejected at construction.

## 4. The layers

Each layer is an independent gate. Together they enforce the invariants above.

### L1 — Sanitizer build (AddressSanitizer + UndefinedBehaviorSanitizer)
A CI job builds gem5 with `--with-asan --with-ubsan` and runs the entire smoke +
property suite under it. This is the single highest-value layer: the memory
class of bugs found this cycle (out-of-bounds refresh, ECC use-after-free,
over-read) are exactly what ASan/UBSan flag automatically.
- Artifact: a `sanitizer-build` job in `.github/workflows/hammersim-ci.yml`.
- Enforces: I4, and the memory-safety substrate of every other invariant.

### L2 — Property / invariant tests
A small harness under `tests/hammersim/` that runs gem5 configs and asserts I1–I8
by comparing traces, stat counters, and exit status. Wired as a required CI
check. Each invariant maps to one property test:
- `prop_reproducibility` (I1), `prop_optin_isolation` (I2),
  `prop_corruption_noperturb` (I3, promoting the existing CI diff into the
  harness), `prop_edge_safety` (I4, run under L1), `prop_ecc_soundness` (I5),
  `prop_monotonicity` (I6), `prop_conservation` (I7),
  `prop_mitigation_efficacy` (I8).
- Artifact: `tests/hammersim/properties/*.py` + a `run_properties.py` driver.

### L3 — Golden regression tests
The existing deterministic smoke tests (`hammersim_smoke.py`,
`hammersim_trr_smoke.py`, `hammersim_rng_smoke.py`) plus a stored expected-output
snapshot (flip counts, corrected/detected counts, per-scenario rows/cols). A
diff against the snapshot catches silent output drift. New scenarios are added
here whenever a feature lands (see §6).
- Artifact: `tests/hammersim/golden/*.expected` compared in CI.

### L4 — Differential fuzzing
A harness that generates N randomized cases — random `--seed`, device map,
attack pattern, row range, and mitigation variant — runs each, and asserts I1
and I4–I7 plus zero crashes / zero sanitizer reports. Small N on each PR, large N
on a nightly schedule. Catches latent bugs on input combinations no hand-written
test covers.
- Artifact: `tests/hammersim/fuzz/fuzz_hammersim.py`, a nightly workflow.

### L5 — Coverage gate
`llvm-cov`/`gcov` over the L2+L3 suite, reporting line and branch coverage for
`src/mem/dram_interface.cc`. CI fails if RowHammer-core coverage drops below a
threshold or leaves a designated critical path (e.g. TRR table admission /
eviction) unexercised. This is what stops a code path from silently going
untested — the gap noted for the TRR sampling logic.
- Artifact: a `coverage` CI job + a checked-in `coverage-floor.txt`.

### L6 — Process and governance
- Branch protection on `develop`: L1, L2, L3, and the existing
  `build-and-smoke-test` are required checks before merge.
- An adversarial-review checklist (§7) applied to every RowHammer-touching PR.
- A periodic independent audit (the multi-agent review used this cycle),
  triggered for changes to fault selection, addressing, or ECC.

## 5. Sequencing and acceptance criteria

| Phase | Delivers | Done when |
| --- | --- | --- |
| 1 | L1 sanitizer CI job | Full smoke suite runs clean under ASan+UBSan in CI |
| 2 | L2 property harness (I1–I8) | All eight property tests pass and are required checks |
| 3 | L3 golden snapshots | Snapshot diff wired in; intentional changes require an explicit snapshot update |
| 4 | L4 fuzz harness | Nightly fuzz job green over ≥1000 cases; PR job over a small N |
| 5 | L5 coverage gate + L6 process | Coverage floor enforced; branch protection and checklist in place |

Phases 1 and 2 carry most of the value and land first.

## 6. Playbook: adding a test when a feature lands

Every new HammerSim behavior ships with verification in the same PR:
1. State the behavior as one or more of the invariants in §3 (extend §3 if it is
   genuinely new).
2. Add a deterministic golden scenario (L3) demonstrating the intended output.
3. Add or extend a property test (L2) if the behavior implies a new invariant.
4. If the behavior adds a new code path, confirm L5 coverage includes it.
5. The PR does not merge until L1–L3 are green for the new test.

## 7. Adversarial-review checklist (RowHammer-touching PRs)

- Reconstructed addresses are bounds-checked and interleaving-correct.
- Every RNG draw is from a seeded, reproducible stream; observational features
  (corruption, tracing) draw from a stream separate from fault selection.
- All table / vector indexing on `row ± k` is guarded at both edges.
- ECC state is captured before corruption, cleared on write, and retained while
  uncorrectable.
- `enable_rowhammer=False` touches no stock data path.
- New stats are registered so they appear in `stats.txt`.
- New configs set `enable_rowhammer` explicitly and select a device map.

## 8. Definition of "working as intended"

A revision is considered verified when, on that exact commit: L1 (sanitizers),
L2 (all invariants), and L3 (golden snapshots) are green; L5 coverage is at or
above the floor; and, for changes in scope §2, the §7 checklist is signed in the
PR. This is reproducible by anyone from a clean checkout.

## 9. Boundaries of confirmation

- The vendor TRR variants are research approximations of proprietary hardware;
  the tests confirm the *modeled* behavior is self-consistent and effective, not
  that it matches a specific real DIMM.
- The ECC model is functional (bit-accurate correction/detection), not
  timing-accurate.
- Full-system guest workloads depend on caller-supplied kernel/disk/KVM assets;
  CI verifies those configurations load and parse, not that a specific guest
  binary reproduces a flip.
- Compressed device maps (`*.json.zip`) are validated only after expansion; the
  runtime requires an uncompressed path.
