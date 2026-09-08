"""Verify functional corruption does not perturb HammerSim fault selection."""

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
parser.add_argument("--memory-corruption", action="store_true")
args = parser.parse_args()


class HammerSimRngDRAM(DDR4_2400_8x8):
    enable_rowhammer = True
    device_file = os.path.join(
        os.getcwd(), "util/hammersim/rng-smoke-device-map.json"
    )
    ranks_per_channel = 1
    rowhammer_threshold = 1
    single_sided_prob = 1
    double_sided_prob = 1
    half_double_prob = 1
    enable_memory_corruption = args.memory_corruption
    corruption_seed = 12345
    rh_stat_dump = True
    rh_stat_file = os.path.join(m5.options.outdir, "rowhammer.trace")


system = System()
system.clk_domain = SrcClockDomain(
    clock="1GHz", voltage_domain=VoltageDomain()
)
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("16MiB")]
system.generator = PyTrafficGen()
system.mem_ctrl = MemCtrl(dram=HammerSimRngDRAM(range=system.mem_ranges[0]))
system.membus = L2XBar()
system.membus.cpu_side_ports = system.generator.port
system.mem_ctrl.port = system.membus.mem_side_ports


def traffic(generator):
    row_stride = 8 * 1024 * 16
    aggressor = row_stride
    separator = row_stride * 8

    # Each aggressor ACT selects another weak column in victim row 2. The
    # separator forces the next aggressor access to issue a fresh ACT.
    for _ in range(12):
        for address in (aggressor, separator):
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

    yield generator.createExit(0)


root = Root(full_system=False, system=system)
m5.instantiate()
system.generator.start(traffic(system.generator))
exit_event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
