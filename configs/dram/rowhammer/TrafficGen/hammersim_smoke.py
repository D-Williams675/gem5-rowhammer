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
        os.getcwd(), "util/hammersim/smoke-device-map.json"
    )
    ranks_per_channel = 1
    rowhammer_threshold = 3
    single_sided_prob = 1
    double_sided_prob = 1
    half_double_prob = 1
    half_double_activation_threshold = 3
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
    # DDR4_2400_8x8 has an 8 KiB rank row buffer and 16 banks. Multiples of
    # this stride therefore select rows in bank 0.
    row_stride = 8 * 1024 * 16
    single_aggressor = row_stride
    single_victim = row_stride * 2
    first_double_aggressor = row_stride * 5
    double_victim = row_stride * 6
    second_double_aggressor = row_stride * 7
    half_double_victim = row_stride * 13
    half_double_relay = row_stride * 14
    half_double_far_aggressor = row_stride * 15
    double_bit_victim = row_stride * 25
    double_bit_aggressor = row_stride * 24

    # Three ACTs to row 1 produce one single-sided flip in vulnerable row 2.
    for address in (
        single_aggressor,
        row_stride * 8,
        single_aggressor,
        row_stride * 9,
        single_aggressor,
        single_victim,
        # ECC correction makes the weak cell eligible to flip again.
        single_aggressor,
        row_stride * 10,
        single_aggressor,
        row_stride * 11,
        single_aggressor,
        single_victim,
        # Rows 5 and 7 jointly contribute three ACTs to vulnerable row 6.
        first_double_aggressor,
        row_stride * 11,
        second_double_aggressor,
        row_stride * 12,
        second_double_aggressor,
        double_victim,
        # A relay ACT and three far-aggressor ACTs exercise Half-Double.
        half_double_relay,
        half_double_far_aggressor,
        row_stride * 20,
        half_double_far_aggressor,
        row_stride * 21,
        half_double_far_aggressor,
        half_double_victim,
        # Two threshold crossings flip separate bytes in one ECC word. The
        # final read must detect, but not correct, the double-bit error.
        double_bit_aggressor,
        row_stride * 30,
        double_bit_aggressor,
        row_stride * 31,
        double_bit_aggressor,
        row_stride * 32,
        double_bit_aggressor,
        row_stride * 30,
        double_bit_aggressor,
        row_stride * 31,
        double_bit_aggressor,
        double_bit_victim,
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

    yield generator.createExit(0)


root = Root(full_system=False, system=system)
m5.instantiate()
system.generator.start(traffic(system.generator))
exit_event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
