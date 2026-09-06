# Copyright (c) 2021 The Regents of the University of California
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

"""
This gem5 configuation script runs `rowhammer-test` on the rowhammer model of
gem5.

This is setup is the close to the simplest setup possible using the gem5
library. It does not contain any kind of caching, IO, or any non-essential
components.

Usage
-----

```
scons build/X86/gem5.opt
./build/X86/gem5.opt \
  configs/dram/rowhammer/FSConfigs/test-scripts/x86-rowhammer-test.py \
  --binary /path/to/x86-rowhammer-workload
```
"""

import argparse
import os
from gem5.isas import ISA
from gem5.utils.requires import requires
from gem5.resources.resource import CustomResource
from gem5.components.memory import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.cachehierarchies.classic.no_cache import NoCache
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.simulate.simulator import Simulator

parser = argparse.ArgumentParser(
    description="Run an x86 SE-mode workload against HammerSim."
)
parser.add_argument("--binary", required=True, help="Path to an x86 workload.")
args = parser.parse_args()
if not os.path.isfile(args.binary):
    parser.error(f"workload does not exist: {args.binary}")

# This check ensures the gem5 binary is compiled to the x86 ISA target. If not,
# an exception will be thrown.
requires(isa_required=ISA.X86)

# In this setup we don't have a cache. `NoCache` can be used for such setups.
cache_hierarchy = NoCache()

# We use a single channel DDR3_1600 memory system
memory = SingleChannelDDR3_1600(size="1GB")
memory._dram_class.enable_rowhammer = True
memory._dram_class.device_file = os.path.join(
    os.getcwd(), "util/hammersim/synthetic-device-map.json"
)
memory._dram_class.trr_variant = 0

# We use a simple Timing processor with one core.
processor = SimpleProcessor(
    cpu_type=CPUTypes.TIMING, num_cores=1, isa=ISA.X86
)

# The gem5 library simble board which can be used to run simple SE-mode
# simulations.
board = SimpleBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

# Run the caller-supplied x86 RowHammer workload.
board.set_se_binary_workload(
    CustomResource(os.path.abspath(args.binary))
)

# Lastly we run the simulation.
simulator = Simulator(board=board, full_system=False)
simulator.run()  # max_ticks = 7000000000)

print(
    "Exiting @ tick {} because {}.".format(
        simulator.get_current_tick(),
        simulator.get_last_exit_event_cause(),
    )
)
