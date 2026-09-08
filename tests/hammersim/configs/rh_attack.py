"""Parameterized HammerSim attack used by the property-test harness.

A single, deterministic single-sided hammer of one aggressor row against the
victim row directly above it, with every HammerSim knob exposed on the command
line so the property driver (tests/hammersim/run_properties.py) can vary one
thing at a time and diff the results. Probabilities default to 1 so a flip is
deterministic once the disturbance threshold is crossed.
"""

import argparse
import os

import m5
from m5.objects import (
    AddrRange,
    DDR4_2400_8x8,
    L2XBar,
    MemCtrl,
    PyTrafficGen,
    Root,
    SrcClockDomain,
    System,
    VoltageDomain,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--device-file", default="util/hammersim/smoke-device-map.json")
parser.add_argument("--enable-rowhammer", action="store_true")
parser.add_argument("--rowhammer-threshold", type=int, default=3)
parser.add_argument("--enable-memory-corruption", action="store_true")
parser.add_argument("--enable-ecc", action="store_true")
parser.add_argument("--ecc-algorithm", type=int, default=0)
parser.add_argument("--trr-variant", type=int, default=0)
parser.add_argument("--aggressor-row", type=int, default=1)
parser.add_argument("--hammers", type=int, default=6)
parser.add_argument("--corruption-seed", type=int, default=5489)
parser.add_argument("--seed", type=int, default=None)
parser.add_argument("--trace-file", default=None)
args = parser.parse_args()

# Optionally seed gem5's global RNG so the property driver can test both
# determinism (same seed -> identical) and sensitivity (different seed differs).
if args.seed is not None:
    try:
        from _m5.core import seedRandom
        seedRandom(args.seed)
    except Exception:
        pass

trace_file = args.trace_file or os.path.join(m5.options.outdir, "rowhammer.trace")

# DDR4_2400_8x8: 8 KiB rank row buffer, 16 banks. Multiples of this stride
# select successive rows within bank 0.
ROW_STRIDE = 8 * 1024 * 16


class AttackDRAM(DDR4_2400_8x8):
    enable_rowhammer = args.enable_rowhammer
    device_file = os.path.join(os.getcwd(), args.device_file)
    ranks_per_channel = 1
    rowhammer_threshold = args.rowhammer_threshold
    single_sided_prob = 1
    double_sided_prob = 1
    half_double_prob = 1
    trr_variant = args.trr_variant
    trr_threshold = 1
    counter_table_length = 4
    companion_table_length = 4
    companion_threshold = 1
    para_probability_denominator = 1
    enable_memory_corruption = args.enable_memory_corruption
    enable_ecc = args.enable_ecc
    ecc_algorithm = args.ecc_algorithm
    corruption_seed = args.corruption_seed
    rh_stat_dump = True
    rh_stat_file = trace_file


system = System()
system.clk_domain = SrcClockDomain(clock="1GHz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("16MiB")]
system.generator = PyTrafficGen()
system.mem_ctrl = MemCtrl(dram=AttackDRAM(range=system.mem_ranges[0]))
system.membus = L2XBar()
system.membus.cpu_side_ports = system.generator.port
system.mem_ctrl.port = system.membus.mem_side_ports


def traffic(generator):
    aggressor = ROW_STRIDE * args.aggressor_row
    victim = ROW_STRIDE * (args.aggressor_row + 1)
    # A separator ACT to a distant row forces the next aggressor access to
    # issue a fresh ACT (disturbance grows on ACT, not on open-row hits).
    separator = ROW_STRIDE * (args.aggressor_row + 64)
    for _ in range(args.hammers):
        for address in (aggressor, separator):
            yield generator.createLinear(
                100000, address, address + 64, 64, 1000, 1000, 100, 64
            )
    # Read the victim so ECC has a chance to see any corrupted word.
    yield generator.createLinear(
        100000, victim, victim + 64, 64, 1000, 1000, 100, 64
    )
    yield generator.createExit(0)


root = Root(full_system=False, system=system)
m5.instantiate()
system.generator.start(traffic(system.generator))
exit_event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
