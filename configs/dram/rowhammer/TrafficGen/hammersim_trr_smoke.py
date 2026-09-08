"""Deterministic HammerSim TRR/PARA mitigation smoke test."""

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
parser.add_argument("--variant", required=True, type=int)
args = parser.parse_args()


class HammerSimMitigatedDRAM(DDR4_2400_8x8):
    enable_rowhammer = True
    device_file = os.path.join(
        os.getcwd(), "util/hammersim/smoke-device-map.json"
    )
    ranks_per_channel = 1
    # A 100% PARA refresh must suppress even a threshold-one disturbance.
    # Table-based variants use a high threshold because they act on the
    # periodic refresh cadence, after this short traffic burst.
    rowhammer_threshold = 1 if args.variant == 5 else 1_000_000
    single_sided_prob = 1
    double_sided_prob = 1
    half_double_prob = 1
    trr_variant = args.variant
    trr_threshold = 1
    counter_table_length = 4
    companion_table_length = 4
    companion_threshold = 1
    para_probability_denominator = 1
    trr_stat_dump = True
    trr_stat_file = os.path.join(m5.options.outdir, "trr.trace")


system = System()
system.clk_domain = SrcClockDomain(
    clock="1GHz", voltage_domain=VoltageDomain()
)
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("16MiB")]
system.generator = PyTrafficGen()
system.mem_ctrl = MemCtrl(
    dram=HammerSimMitigatedDRAM(range=system.mem_ranges[0])
)
system.membus = L2XBar()
system.membus.cpu_side_ports = system.generator.port
system.mem_ctrl.port = system.membus.mem_side_ports


def traffic(generator):
    row_stride = 8 * 1024 * 16
    # One ACT must be enough to admit/track the row at threshold 1. This also
    # catches an off-by-one in the Vendor A companion-table admission path.
    for row in (1,):
        address = row * row_stride
        yield generator.createLinear(
            100000,
            address,
            address + 64,
            64,
            1000,
            1000,
            100,
            64,
        )

    # Vendor A runs its mitigation every ninth refresh; 100 us covers more
    # than one such period for DDR4_2400_8x8.
    yield generator.createIdle(100_000_000)
    yield generator.createExit(0)


root = Root(full_system=False, system=system)
m5.instantiate()
system.generator.start(traffic(system.generator))
exit_event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
