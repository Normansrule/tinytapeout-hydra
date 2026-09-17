#!/usr/bin/env python3
"""
mutate_sim.py -- every cocotb test must be able to fail.

Session 179. The formal targets have mutate.py; the tile's cocotb suite had
nothing equivalent, so a test that could never fail would go unnoticed. Each
mutation below breaks one documented behaviour in a scratch copy of the
tile, regenerates project.v with regen.sh, runs the whole suite, and requires
that the NAMED test fails. A mutation caught only by some other test is
reported, because that means the named test is not doing its job.

Anchor rules (stale-anchor pattern, s135/s136/s178/s178m): each anchor is a
distinctive fragment and must match EXACTLY ONCE in the pristine file, or the
run stops before anything is built.

Usage: python3 test/mutate_sim.py            (from the tile repo root)
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# NOT MUTATED, and why. Session 179 ran `.csn_i(~reg_mode | ui_in[2])` ->
# `.csn_i(ui_in[2])`, letting legacy pin traffic assemble frames inside the SPI
# block, and it SURVIVED the whole suite. That is correct: every register
# output is gated by reg_mode at the mom_top instance, and reg_mode can only
# change while reset is asserted -- which also clears the register block. So
# the gate has no observable effect at the pins; it is isolation, not
# behaviour, and it stays for that reason. A mutation nothing can observe is
# not evidence of a weak test, and pretending otherwise by deleting the check
# would be the wrong lesson. Do not re-add it as a mutation.

MUTATIONS = [
    # (label, file, anchor, replacement, test that must fail)
    ("PARAM_LOCK ignored",
     "src/rtl/hydra_tt_regs.sv", "A_PARAM: if (!param_lock_q) begin", "A_PARAM: if (1'b1) begin",
     "test_reg_param_retune_moves_the_decision"),
    ("frame length not checked",
     "src/rtl/hydra_tt_regs.sv", "(n_data == reg_len(cmd_addr));", "1'b1;",
     "test_reg_torn_frames_change_nothing"),
    ("GO accepts a torn descriptor",
     "src/rtl/hydra_tt_regs.sv", "do_go && wd_ok && !pending_q", "do_go && !pending_q",
     "test_reg_torn_frames_change_nothing"),
    ("HOLD ignored",
     "src/rtl/hydra_tt_regs.sv", "assign disp_accept     = ~hold_q;", "assign disp_accept     = 1'b1;",
     "test_reg_hold_backpressure"),
    ("calibration freeze not wired",
     "src/rtl/hydra_tt_regs.sv", "assign csr_cal_freeze  = cal_freeze_q;", "assign csr_cal_freeze  = 1'b0;",
     "test_reg_completion_calibration_and_fence"),
    ("PARAM engine field shifted",
     "src/rtl/hydra_tt_regs.sv", "csr_engine <= wbuf[45:43];", "csr_engine <= wbuf[44:42];",
     "test_reg_param_retune_moves_the_decision"),
    ("status byte missing during command",
     "src/rtl/hydra_tt_regs.sv", "if (!have_cmd)   tx_byte = status_w[15:8];", "if (!have_cmd)   tx_byte = 8'h00;",
     "test_reg_strap_id_and_defaults"),
    ("read bytes in wrong order",
     "src/rtl/hydra_tt_regs.sv", "7'((len - 5'd1 - k)) * 7'd8;", "7'(k) * 7'd8;",
     "test_reg_strap_id_and_defaults"),
    ("LASTWD not captured",
     "src/rtl/hydra_tt_regs.sv", "r_lastwd <= disp_wd;", "r_lastwd <= r_lastwd;",
     "test_reg_crossover_and_readback"),
    ("clear-sticky leaves frame error",
     "src/rtl/hydra_tt_regs.sv", "s_stale <= 1'b0;\n        s_frame <= 1'b0;", "s_stale <= 1'b0;\n",
     "test_reg_torn_frames_change_nothing"),
    ("margin pins linear",
     "src/rtl/hydra_tt_regs.sv", "mlog = (b >= 14) ? 4'd15 : 4'(b + 1);", "mlog = 4'(b >> 4);",
     "test_reg_margin_pins_are_log_scaled"),
    ("SPI shifts LSB first",
     "src/rtl/hydra_tt_spi.sv", "assign cipo_o = tx_sr[7];", "assign cipo_o = tx_sr[0];",
     "test_reg_strap_id_and_defaults"),
    ("strap selects register mode by default",
     "src/tt_um_hydra_mom.sv", "(ui_in[7:4] == 4'hA)", "(ui_in[7:4] != 4'hA)",
     "test_roofline_crossover"),
    ("legacy go not edge detected",
     "src/tt_um_hydra_mom.sv", "~reg_mode & go   & ~go_q;", "~reg_mode & go;",
     "test_edge_detected_go"),
]

RESULT_RE = re.compile(r"\*\*\s+(test\w*)\.(\w+)\s+(PASS|FAIL)")


def run_suite(tree):
    subprocess.run(["bash", "src/regen.sh"], cwd=tree, check=True,
                   stdout=open(tree / "src" / "project.v", "w"))
    shutil.rmtree(tree / "test" / "sim_build", ignore_errors=True)
    # The Makefile resolves sources through $(PWD). A subprocess inherits PWD
    # from its parent, not from cwd, so without this every mutated copy would
    # silently simulate whichever tree the script was launched from.
    env = dict(os.environ, PWD=str(tree / "test"))
    p = subprocess.run(["make", "-s"], cwd=tree / "test", capture_output=True,
                       text=True, timeout=900, env=env)
    return {m.group(2): m.group(3) for m in RESULT_RE.finditer(p.stdout + p.stderr)}


def main():
    for label, f, anchor, _, _ in MUTATIONS:
        n = (ROOT / f).read_text().count(anchor)
        if n != 1:
            print(f"STALE ANCHOR '{label}': {f} matches {n} times: {anchor!r}")
            sys.exit(1)

    bad = 0
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td) / "tile"
        shutil.copytree(ROOT, base, ignore=shutil.ignore_patterns("sim_build", ".git", "*.vcd"))
        res = run_suite(base)
        fails = [t for t, v in res.items() if v != "PASS"]
        print(f"baseline: {len(res)} tests, {len(fails)} failing")
        if not res or fails:
            print("=== BASELINE NOT GREEN -- NOTHING COUNTS ===")
            sys.exit(1)
        expected = set(res)

        for label, f, anchor, repl, must_fail in MUTATIONS:
            tree = pathlib.Path(td) / "mut"
            shutil.rmtree(tree, ignore_errors=True)
            shutil.copytree(base, tree)
            src = (tree / f).read_text()
            (tree / f).write_text(src.replace(anchor, repl))
            try:
                r = run_suite(tree)
            except subprocess.CalledProcessError:
                print(f"  KILLED    {label}  (does not build)")
                continue
            missing = expected - set(r)
            failed = sorted(t for t, v in r.items() if v != "PASS") + sorted(missing)
            if must_fail in failed:
                print(f"  KILLED    {label}  by {must_fail}"
                      + (f" (+{len(failed) - 1} more)" if len(failed) > 1 else ""))
            elif failed:
                print(f"  WRONG TEST {label}: {must_fail} passed, caught by {failed}")
                bad += 1
            else:
                print(f"  SURVIVED  {label}")
                bad += 1

    if bad:
        print(f"=== {bad} PROBLEM(S) ===")
        sys.exit(1)
    print("=== ALL SIMULATION MUTATIONS KILLED ===")


if __name__ == "__main__":
    main()
