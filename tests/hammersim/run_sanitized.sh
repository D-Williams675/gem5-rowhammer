#!/bin/bash
# Layer 1 of VERIFICATION.md: run the HammerSim suite under a gem5 built with
# AddressSanitizer + UBSan and fail on any memory-safety issue in our code.
#
# ASan halts: gem5 core is ASan-clean, so any AddressSanitizer abort -- in the
# smoke tests or in the property harness's edge-row runs -- is a real heap bug.
# UBSan is advisory: gem5 core has benign startup undefined behavior (a
# misaligned reference in src/mem/port.cc during static init) that must not
# abort the run, so we do NOT halt on UBSan and instead scan its findings for
# our own source files.
#
# Usage: tests/hammersim/run_sanitized.sh [path/to/gem5.opt]
# Run from the repository root. Exits non-zero if anything fails.
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
GEM5="${1:-build/X86/gem5.opt}"
CFG=configs/dram/rowhammer/TrafficGen
OURS='dram_interface|mem_interface|hammersim'

export ASAN_OPTIONS="detect_leaks=0:halt_on_error=1:abort_on_error=1"
export UBSAN_OPTIONS="print_stacktrace=1"

if [ ! -x "$GEM5" ]; then echo "gem5 binary not found: $GEM5" >&2; exit 2; fi
fail=0

run() {  # label config [args...]
  local label="$1"; shift
  local out="m5out-san-$label"
  "$GEM5" --outdir="$out" "$@" > "$out.log" 2>&1
  local ec=$?
  local flag=""
  grep -q "AddressSanitizer" "$out.log" && flag="$flag ASAN"
  grep -E "runtime error:" "$out.log" 2>/dev/null | grep -qE "$OURS" && flag="$flag UBSAN-OURS"
  if [ "$ec" -ne 0 ] || [ -n "$flag" ]; then fail=1; fi
  printf '%-14s exit=%s%s\n' "$label" "$ec" "$flag"
}

echo "== HammerSim smoke suite under ASan+UBSan =="
run stock "$CFG/test-scripts/simple_dram.py"
run smoke "$CFG/hammersim_smoke.py"
for v in 1 2 4 5 6; do
  run "trr$v" "$CFG/hammersim_trr_smoke.py" --variant "$v"
done

echo "== property harness (invariants I1-I7) under ASan =="
python3 tests/hammersim/run_properties.py "$GEM5" || fail=1

echo "== UBSan findings in our files (should be none) =="
if grep -rEh "runtime error:" m5out-san-*.log 2>/dev/null | grep -E "$OURS"; then
  echo "!! UBSan flagged our code"; fail=1
else
  echo "none (gem5-core startup UBSan noise ignored)"
fi

echo "== RESULT: $([ $fail -eq 0 ] && echo PASS || echo FAIL) =="
exit "$fail"
