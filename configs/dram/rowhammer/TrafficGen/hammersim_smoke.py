"""Short deterministic HammerSim functional-corruption/ECC smoke test."""

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


class HammerSimDRAM(DDR4_2400_8x8):
    enable_rowhammer = True
    device_file = os.path.join(
        os.getcwd(), "util/hammersim/synthetic-device-map.json"
    )
    ranks_per_channel = 1
    rowhammer_threshold = 3
    single_sided_prob = 1
    double_sided_prob = 1
    half_double_prob = int(1e9)
    enable_memory_corruption = True
    enable_ecc = True
    ecc_algorithm = 1
    trr_variant = 0


system = System()
system.clk_domain = SrcClockDomain(
    clock="1GHz", voltage_domain=VoltageDomain()
)
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("16MiB")]
system.generator = PyTrafficGen()
system.mem_ctrl = MemCtrl(dram=HammerSimDRAM(range=system.mem_ranges[0]))
system.membus = L2XBar()
system.membus.cpu_side_ports = system.generator.port
system.mem_ctrl.port = system.membus.mem_side_ports


def traffic(generator):
    # DDR4_2400_8x8 has an 8 KiB rank row buffer and 16 banks. These
    # addresses therefore select rows 1, 4, and 2 of bank 0 respectively.
    row_stride = 8 * 1024 * 16
    aggressor = row_stride
    separator_one = row_stride * 4
    separator_two = row_stride * 5
    victim = row_stride * 2

    for address in (
        aggressor,
        separator_one,
        aggressor,
        separator_two,
        aggressor,
    ):
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

    # The third aggressor ACT deterministically flips one victim bit. Reading
    # the victim exercises the functional SECDED correction path.
    yield generator.createLinear(
        100000,
        victim,
        victim + 64,
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
