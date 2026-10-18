#!/bin/bash
# Regenerate project.v from the SystemVerilog sources beside it.
#
# The sources live in src/rtl/ rather than being referenced out of the parent
# project, because a TinyTapeout submission is a STANDALONE REPO. The first
# version reached up three directory levels into the HYDRA-130 tree, which
# worked here and would have broken the moment the tile was cloned on its own
# -- taking the netlist-versus-source check with it, which is the one check
# that catches shipping logic that was never verified.
#
# tools/tt_check.sh diffs this output against the committed project.v.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
#
# Lint (2026-10-12): the harden lints project.v with Verilator --Wall, and the
# sources are written so that it is clean. One class of warning is sv2v's own:
# it copies every package constant a module could use into that module as a
# localparam, and it writes port and declaration widths as numbers, so some
# constants that the SystemVerilog does use end up referenced nowhere in the
# output (UNUSEDPARAM). The filter below drops a one-line localparam only if
# its name appears nowhere else in its module. Removing an unreferenced
# constant cannot change the design.
sv2v "$D/rtl/hydra_rst_sync.sv" "$D/rtl/mom_pkg.sv" "$D/rtl/mom_features.sv" "$D/rtl/mom_param_rom.sv" \
     "$D/rtl/mom_cost_engine.sv" "$D/rtl/mom_calibrate.sv" \
     "$D/rtl/mom_select.sv" "$D/rtl/mom_scoreboard.sv" "$D/rtl/mom_top.sv" \
     "$D/rtl/hydra_tt_spi.sv" "$D/rtl/hydra_tt_regs.sv" \
     "$D/tt_um_hydra_mom.sv" |
python3 -c '
import re, sys
src = sys.stdin.read()
out = []
for mod in re.split(r"(?m)^(?=module )", src):
    keep = []
    for line in mod.split("\n"):
        m = re.match(r"\s*localparam (?:\[[^\]]*\] )?(\w+) = [^;]+;\s*$", line)
        if m and len(re.findall(r"\b" + m.group(1) + r"\b", mod)) == 1:
            continue
        keep.append(line)
    out.append("\n".join(keep))
sys.stdout.write("".join(out))
'
