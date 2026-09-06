# HammerSim RowHammer model

HammerSim extends gem5's DRAM interface with opt-in RowHammer disturbance,
functional data corruption, simplified functional SECDED, and several
research-oriented Target Row Refresh (TRR) models.

The RowHammer model is disabled by default. An ordinary gem5 DRAM
configuration therefore behaves like upstream gem5 and does not load a device
map or allocate HammerSim tracking state.

## Clone and build

HammerSim uses nlohmann/json as a Git submodule:

```sh
git clone --recurse-submodules https://github.com/D-Williams675/gem5-rowhammer.git
cd gem5-rowhammer
scons build/NULL/gem5.opt -j"$(nproc)"
```

If the repository was cloned without submodules, run:

```sh
git submodule update --init --recursive
```

The `NULL` build is sufficient for the synthetic traffic-generator
configurations. Build `X86` for the full-system configurations.

## Quick verification

The deterministic smoke test performs three aggressor ACTs, functionally flips
one bit in the victim row, reads the victim, and corrects the bit through the
simplified SECDED model:

```sh
build/NULL/gem5.opt --outdir=m5out-hammersim \
  configs/dram/rowhammer/TrafficGen/hammersim_smoke.py
```

The resulting `stats.txt` should report one total bit flip, one functionally
corrupted bit, and one ECC correction. The `HammerSim CI` GitHub workflow
builds gem5 and checks these values automatically. It also runs a stock DRAM
configuration with HammerSim disabled.

## Configuration

Set HammerSim parameters on a `DRAMInterface` subclass:

```python
class HammerSimDRAM(DDR4_2400_8x8):
    enable_rowhammer = True
    device_file = "util/hammersim/synthetic-device-map.json"
    rowhammer_threshold = 50000
    single_sided_prob = int(1e7)
    double_sided_prob = int(1e5)
    half_double_prob = int(1e9)
    trr_variant = 0
```

Important parameters:

- `enable_rowhammer`: Enables disturbance tracking and device-map loading.
  It defaults to `False`.
- `device_file`: Path to an uncompressed JSON device map. It is required when
  HammerSim is enabled.
- `rowhammer_threshold`: Number of relevant ACT commands per bit-flip
  opportunity.
- `single_sided_prob`, `double_sided_prob`, and `half_double_prob`:
  Positive probability denominators. For example, `1000` means a probability
  of exactly 1/1000 at each corresponding opportunity. HammerSim uses gem5's
  seeded random-number generator, so simulations respect gem5's reproducible
  random seed.
- `enable_memory_corruption`: Applies selected bit flips to gem5's backing
  memory. It requires `enable_rowhammer=True`.
- `enable_ecc`: Enables simplified functional SECDED. It requires functional
  corruption and `ecc_algorithm=1`.
- `synthetic_traffic`: Retained for configuration compatibility. Probability
  opportunities are now consistently evaluated at threshold boundaries for
  all workload types.
- `rh_stat_dump` and `rh_stat_file`: Append RowHammer trace information at
  full-refresh boundaries.

All thresholds and probability denominators must be non-zero. Invalid
combinations fail during configuration instead of failing later in a
simulation.

## Device-map format

A device map lists weak byte-columns by rank, bank, and row:

```json
{
  "0": {
    "4": {
      "58": [18, 151, 272]
    }
  }
}
```

Keys are strings because they are JSON object keys. Columns must be valid byte
offsets within the configured rank row buffer. Invalid values are ignored with
a warning. Missing ranks, banks, or rows mean that no modeled weak column is
available at that location.

For small synthetic tests, any level may use the wildcard key `"*"`:

```json
{
  "*": {
    "*": {
      "*": [0, 1, 2, 3]
    }
  }
}
```

`util/hammersim/synthetic-device-map.json` provides a ready-to-use wildcard
map. Hardware-derived maps for Vendor B are in
`util/hammersim/row_experiment_vendor_b/`. The large
`prob-005.json.zip` archive must be decompressed before it can be supplied as
`device_file`.

HammerSim selects an unflipped weak column without mutating the device map.
Writes make affected columns eligible again. The set of already-flipped
columns is sparse, so enabling HammerSim no longer allocates a dense bitmap for
every cell in memory.

## Disturbance and corruption behavior

Only ACT commands increase disturbance counters. Repeated column commands to
an already-open row do not count as additional hammers. Reading or writing a
victim row restores its modeled disturbance state.

At a threshold boundary, HammerSim classifies the opportunity as
single-sided, double-sided, or Half-Double, applies the configured probability,
and selects an available weak column from the device map. Functional
corruption reconstructs the exact physical victim address from rank, bank,
row, and byte column, including rank and channel interleaving. It then flips
one randomly selected bit in that byte.

Functional corruption currently supports `RoRaBaChCo` and `RoRaBaCoCh`
address mappings. Other address mappings remain usable when functional
corruption is disabled.

## TRR variants

The supported `trr_variant` values are:

- `0`: No TRR mitigation.
- `1`: Vendor-A-style per-bank counter table with a companion admission
  table.
- `2`: Vendor-B-style sampled table with one rank-wide hottest-row
  selection.
- `4`: Experimental Vendor-A table without a companion table.
- `5`: PARA, with a 1% probability of refreshing immediately adjacent rows
  after each ACT.
- `6`: Vendor-B-style sampled table with HammerSim's experimental masked-row
  selection.

Variant `3` is rejected because the previous implementation was incomplete.
The vendor mechanisms are research approximations of proprietary hardware, not
claims of exact vendor internals.

TRR tables track rank, bank, row, and ACT count. Full tables replace the entry
with the lowest count. Neighbor refreshes and periodic counter resets are
bounds-checked for edge rows.

## Functional ECC

HammerSim's ECC is functional rather than timing-accurate. When corruption
first touches an aligned 64-bit word, HammerSim records the pristine word.
On a later read:

- one differing bit is restored and counted as corrected;
- two or more differing bits are counted as detected and left corrupted;
- a clean word is removed from tracking.

Writes invalidate ECC tracking for every overlapping 64-bit word. This models
the correction/detection outcome without adding ECC storage, encoding latency,
or decoder timing to the DRAM protocol.

## Full-system configurations

The full-system scripts no longer contain developer-specific host paths or a
hard-coded sudo password. Pass the disk image explicitly and optionally
override the kernel:

```sh
build/X86/gem5.opt \
  configs/dram/rowhammer/FSConfigs/rowhammer-test/x86-rowhammer-with-kvm.py \
  --disk-image /path/to/x86-ubuntu \
  --kernel ~/.cache/gem5/x86-linux-kernel-5.4.49
```

The same paths may be supplied through `HAMMERSIM_DISK_IMAGE` and
`HAMMERSIM_KERNEL`. Use `--guest-command` if the workload is installed at a
different path inside the disk image. The NPB configuration similarly accepts
`--disk-image`, `--kernel`, and `--guest-npb-dir`.

Synthetic traffic and full-system examples are under
`configs/dram/rowhammer/`.

## Implementation map

The main implementation is in:

- `src/mem/DRAMInterface.py`: user-facing parameters;
- `src/mem/dram_interface.hh` and `src/mem/dram_interface.cc`: disturbance,
  TRR, corruption, and ECC behavior;
- `src/mem/mem_interface.hh`: per-bank tracking state;
- `src/mem/SConscript`: the JSON include path.

New mitigation samplers belong in `DRAMInterface::activateBank`. Refresh-time
inhibitors belong in `DRAMInterface::Rank::processRefreshEvent`.
`DRAMInterface::checkRowHammer` contains bit-flip classification and
selection, while `DRAMInterface::doMemoryCorruption` performs the backing
memory mutation.
