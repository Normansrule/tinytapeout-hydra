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
sv2v "$D/rtl/mom_pkg.sv" "$D/rtl/mom_features.sv" "$D/rtl/mom_param_rom.sv" \
     "$D/rtl/mom_cost_engine.sv" "$D/rtl/mom_calibrate.sv" \
     "$D/rtl/mom_select.sv" "$D/rtl/mom_scoreboard.sv" "$D/rtl/mom_top.sv" \
     "$D/tt_um_hydra_mom.sv"
