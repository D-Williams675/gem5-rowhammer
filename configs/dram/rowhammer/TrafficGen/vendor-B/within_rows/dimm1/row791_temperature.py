# Copyright (c) 2021-2025 The Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Synthetic-model variant of row791_2_aggressor_rows.py.
#
# This config forces the synthetic weak-row/weak-cell probability model
# on for EVERY row (prefer_device_map_data = False), even row 791, which
# has real device-map data. It also seeds gem5's global RNG from a
# command-line argument so that runs are reproducible and vary with the
# seed -- exactly what is needed to run many attacks and collect
# per-run bit-flip statistics.
#
# Usage:
#   build/X86/gem5.opt [--outdir=DIR] \
#       configs/.../row791_2_aggressor_rows_synth.py [--seed N] \
#       [--prefer-device-map]
#
# --seed N            : seed for gem5's RNG (default 1). Different seeds
#                       give different synthetic outcomes.
# --prefer-device-map : restore the default behavior (use real device-map
#                       data where available). Omitted => synthetic model.

import argparse

from m5.objects import *
import m5, os

# ----------------------------------------------------------------------
# Parse the script arguments. gem5 forwards everything after the config
# file name to sys.argv, so a normal argparse works here.
# ----------------------------------------------------------------------
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--seed", type=int, default=1,
                    help="Seed for gem5's global RNG (default: 1).")
parser.add_argument("--prefer-device-map", action="store_true",
                    help="Prefer real device-map data over the synthetic "
                         "model (restores the default behavior).")
parser.add_argument("--trace-file", type=str, default=None,
                    help="Path for the RowHammer bit-flip trace. Defaults "
                         "to rh_results/rowhammer_seed<seed>.trace so that "
                         "batch runs over many seeds never collide (the "
                         "trace is opened in append mode).")
# --- Temperature-dependent weak-cell model (SpyHammer) ---
parser.add_argument("--temperature", type=int, default=50,
                    help="DRAM temperature in Celsius (default: 50).")
parser.add_argument("--temp-min", type=int, default=50,
                    help="Minimum modeled temperature (default: 50).")
parser.add_argument("--temp-max", type=int, default=95,
                    help="Maximum modeled temperature (default: 95).")
parser.add_argument("--temp-range-size", type=int, default=5,
                    help="Width of each temperature range in C (default: 5).")
parser.add_argument("--w0-percent", type=float, default=30.0,
                    help="%% of cells weak at all temperatures, W0 "
                         "(default: 30).")
parser.add_argument("--canary-percent", type=float, default=2.0,
                    help="%% of canary cells weak at exactly one temperature "
                         "range (default: 2).")
args = parser.parse_args()

# The RowHammer trace file is opened in append mode by the C++ side, so
# every run must write to its own file or counts from different runs will
# pile up together. Derive a per-seed default and make sure its directory
# exists (the raw std::ofstream on the C++ side will not create it).
if args.trace_file is None:
    trace_file = os.path.join(os.getcwd(), "rh_results",
                              "rowhammer_seed%d_temp%d.trace"
                              % (args.seed, args.temperature))
else:
    trace_file = args.trace_file
os.makedirs(os.path.dirname(os.path.abspath(trace_file)), exist_ok=True)
# Start each run from a clean trace file (append mode would otherwise keep
# stale flips from a previous run using the same path).
open(trace_file, "w").close()

# Seed gem5's global RNG (random_mt) BEFORE m5.instantiate(). The
# DRAMInterface constructor (which runs during instantiate) seeds its own
# probability model RNG from this global RNG, so this makes the synthetic
# model reproducible and controllable by --seed. The binding lives on the
# native _m5.core module (m5.core does not re-export it).
from _m5.core import seedRandom
seedRandom(args.seed)

# Need a couple of standard definitions for the rest of the script to work
# without any issues.
ROW_SIZE = 0x400
TARGET_BANK = 0x4
# Each tick is 1/4th of a pico-second
MIN_PERIOD = 1230000
MAX_PERIOD = 1520000

# From our test set, row 791 is vulnerable on DIMM 1.
TARGET_ROW = 791

# We create a simple memory interface class for evaluating rowhammer
class DRAM_TEST(DDR4_2400_8x8):
    """
    This class has 8 banks per rank.
    The rowbuffer size is 1KiB
    """
    # Use the correct device map
    device_file = os.path.join(os.getcwd(),
                    "util/hammersim/row_experiment_vendor_b/dimm1.bank-4.json")
    ranks_per_channel = 1
    # TRR is already bypassed to study vulnerable rows.
    trr_variant = 0
    trr_threshold = 16834
    rowhammer_threshold = 45000
    counter_table_length = 6
    # companion_table_length = 6
    # Dump the per-flip RowHammer trace so bit flips can be counted
    # (grep -c "Bitflip at" <trace_file>).
    rh_stat_dump = True
    rh_stat_file = trace_file
    # Force the synthetic weak-row/weak-cell probability model on for
    # every row (including rows that have real device-map data), unless
    # --prefer-device-map was passed.
    prefer_device_map_data = args.prefer_device_map
    # Temperature-dependent weak-cell model (SpyHammer). When enabled,
    # cell weakness = W0 (always weak) + canary cells for the current
    # temperature range. Enabled here since this config studies it.
    enable_temperature_model = True
    temperature = args.temperature
    temp_min = args.temp_min
    temp_max = args.temp_max
    temp_range_size = args.temp_range_size
    w0_percent = args.w0_percent
    canary_percent = args.canary_percent
    # There is a very high probability for a bitflip however, bitflips become
    # highly likely as the rowhammer threshold is crossed.
    half_double_prob = 1e18
    # Modeling this based on DDR4 DIMMs
    double_sided_prob = 1e16
    # Single sided rowhammer is rare.
    single_sided_prob = 1e18
    synthetic_traffic = True


duration = int(1e11)

system = System()
system.clk_domain = SrcClockDomain()
system.clk_domain.clock = "4GHz"
system.clk_domain.voltage_domain = VoltageDomain()
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("1GB")]

system.generator0 = PyTrafficGen()
system.generator1 = PyTrafficGen()

system.mem_ctrl = MemCtrl()

system.mem_ctrl.dram = DRAM_TEST(range=system.mem_ranges[0])

system.membus = L2XBar()

system.membus.cpu_side_ports = system.generator0.port
system.membus.cpu_side_ports = system.generator1.port

# for testing the victim row

system.mem_ctrl.port = system.membus.mem_side_ports

# Our victim bank from the collected device map is in bank 4.
def get_data_chunk(row_number, width=8):
    return row_number * 128

# Addresses start from row 292 of bank 4.
def createLinearTraffic0(tgen):
    yield tgen.createLinear(
        duration,  # duration
        AddrRange(str(
            get_data_chunk(TARGET_ROW - 1) + (8 * TARGET_BANK)) + "kB").end,
        AddrRange(str(
            get_data_chunk(TARGET_ROW - 1) + (8 * TARGET_BANK) + 1) + "kB").end,
        64,  # block_size
        MIN_PERIOD,  # min_period
        MAX_PERIOD,  # max_period
        100,  # rd_perc
        0,
    )  # data_limit
    yield tgen.createExit(0)

def createLinearTraffic1(tgen):
    yield tgen.createLinear(
        duration,  # duration
        AddrRange(str(
            get_data_chunk(TARGET_ROW + 1) + (8 * TARGET_BANK)) + "kB").end,
        AddrRange(str(
            get_data_chunk(TARGET_ROW + 1) + (8 * TARGET_BANK) + 1) + "kB").end,
        64,  # block_size
        MIN_PERIOD,  # min_period
        MAX_PERIOD,  # max_period
        100,  # rd_perc
        0,
    )  # data_limit
    yield tgen.createExit(0)

root = Root(full_system=False, system=system)

m5.instantiate()

system.generator0.start(createLinearTraffic0(system.generator0))
system.generator1.start(createLinearTraffic1(system.generator1))

m5.simulate()
