/*
 * tt_um_hydra_mom.sv
 *
 * HYDRA-130 - TinyTapeout spinout of the Mathematical Operation MUX (TT-A)
 * Copyright (c) 2026 Aleksander J. Norman
 * SPDX-License-Identifier: Apache-2.0
 *
 * ===========================================================================
 * WHY TAPE OUT A SCHEDULER ON ITS OWN
 * ===========================================================================
 * The MOM is the novel block in HYDRA-130 and the one a paper would rest on.
 * Everything about it is verified in simulation: 10,000-vector cross-check
 * against an independent model, a closed-loop calibration test, and formal
 * proofs on five modules.
 *
 * None of that is silicon. A TinyTapeout tile costs a fraction of a shuttle
 * slot and answers questions simulation cannot:
 *
 *   - Does the three-cycle dispatch path close timing at a real Fmax?
 *   - What is the actual gate count against a real standard cell library?
 *   - Does the calibration loop converge on hardware, with real latencies
 *     rather than a testbench's fixed delays?
 *
 * A block that survives TinyTapeout silicon has earned its place on the big
 * die. One that does not has cost a few hundred euros instead of a shuttle.
 *
 * ===========================================================================
 * THE PIN PROBLEM
 * ===========================================================================
 * A work descriptor is 128 bits. TinyTapeout gives 8 inputs, 8 outputs, and 8
 * bidirectionals. So the descriptor is shifted in serially, one bit per clock,
 * and the result is read back in parallel.
 *
 * Shifting 128 bits at, say, 10 MHz takes 12.8 us. The dispatch decision that
 * follows takes 3 cycles, 300 ns. The interface is 40x slower than the thing
 * it is testing, which is fine: this measures whether dispatch is CORRECT and
 * what Fmax it closes at, not how fast a descriptor can be loaded.
 *
 * ===========================================================================
 * v3 (2026-10-09): THE RESEARCH TILE
 * ===========================================================================
 * This repository is the silicon experiment, not the product. The full
 * dispatcher, with both host personalities and 8 tags, now lives in the
 * HYDRA-130 chip (hydra-skywater130, mom/), next to the CPU, GPU and TPU it
 * schedules. This tile keeps only what the experiment needs -- the cost
 * model, the scoreboard, calibration, and the register map that observes
 * them -- and drops what costs area and power without answering a question:
 *
 *   LEGACY PERSONALITY REMOVED. The v1 pin protocol needed a 128-bit shift
 *     register, edge detectors and a result latch, and every bit of that
 *     toggled on every shift. The register map sees everything the legacy
 *     pins could, and more (the full 32-bit margin, the descriptor as
 *     dispatched, calibration counters). The chip keeps legacy mode, and its
 *     tb_v1_v2_diff still proves it pin-for-pin against v1.
 *   NO DESCRIPTOR READBACK. v2's LASTWD register read back all 128 bits of
 *     the descriptor as dispatched, which kept every bit alive through every
 *     pipeline stage: 12,600 um^2 for an echo of what the host just sent.
 *   4 TAGS, NOT 8. The scoreboard is the largest block; each tag holds a
 *     start time and a prediction. Four in flight is enough to exercise
 *     exhaustion, back-pressure and out-of-order completion.
 *
 * ===========================================================================
 * PIN MAP (SPI mode 0, SCK <= clk/8; the register map is in hydra_tt_regs.sv)
 * ===========================================================================
 * ui_in[0]     SCK
 * ui_in[1]     COPI
 * ui_in[2]     CSn         idle high; a host that holds it low through reset
 *                          gets one empty frame, which is not an error
 * ui_in[7:3]   unused      (v2 sampled ui_in[7:4] as a personality strap;
 *                          v3 ignores it, so a v2 host still works)
 *
 * uo_out[0]    CIPO
 * uo_out[1]    IRQ         a sticky error flag is set
 * uo_out[4:2]  engine      engine of the last dispatch
 * uo_out[5]    dispatched  sticky until CLEAR_STICKY
 * uo_out[6]    any_busy    at least one tag outstanding
 * uo_out[7]    ready       the MOM can accept a descriptor
 *
 * uio_out[3:0] tag         tag of the last dispatch (0..3)
 * uio_out[7:4] margin      1 + floor(log2(runner-up margin)), 0 if none
 * uio_oe                   all ones: every bidirectional is an output
 *
 * v2 history: v2 carried both personalities, selected by a reset strap
 * (ui_in[7:4] = 4'hA for registers), and fixed the v1 margin nibble, which
 * could only ever read 0 or F.
 *
 * ===========================================================================
 * A LESSON CARRIED OVER FROM ASICIRIFIC
 * ===========================================================================
 * The `tiles` value in info.yaml and the DIE_AREA in the hardened config must
 * agree. On the ASICirific submission they did not, because the project's
 * src/config.json was missing `FP_SIZING: "absolute"`, so LibreLane ignored
 * DIE_AREA and auto-sized the die. DRC, LVS, and timing all passed against the
 * WRONG die, and the only symptom was a boundary XOR failure that looked like
 * a tool bug. It cost three weeks.
 *
 * Use the stock TinyTapeout src/config.json for this project, unmodified. If
 * area needs tuning, change `tiles` in info.yaml and let the flow regenerate
 * the config. Do not hand-edit the floorplan settings.
 * ===========================================================================
 */

`default_nettype none

module tt_um_hydra_mom
  import mom_pkg::*;
(
  input  wire [7:0] ui_in,
  output wire [7:0] uo_out,
  input  wire [7:0] uio_in,
  output wire [7:0] uio_out,
  output wire [7:0] uio_oe,
  input  wire       ena,
  input  wire       clk,
  input  wire       rst_n
);

  // ===========================================================================
  // RESET: asserted asynchronously, RELEASED synchronously
  // ===========================================================================
  // The rst_n pin used to drive every asynchronously-reset flip-flop directly
  // -- about 2,500 of them. Two problems with that, one physical and one
  // logical:
  //
  //   TIMING   every recovery check started at an INPUT PIN, carrying the
  //            input delay the constraints assign to pins (20% of the
  //            period), then crossed a buffer tree to thousands of loads.
  //            The slow corner missed timing even after the clock period was
  //            lengthened from 55 to 66 ns, which is the signature of a path
  //            that does not scale with the clock.
  //   LOGIC    release was asynchronous to the clock, so different
  //            flip-flops could leave reset on different cycles.
  //
  // hydra_rst_sync (formally verified in the parent repository) asserts the
  // moment rst_n falls and releases only after STAGES clean clock edges.
  // Recovery checks now start at a REGISTER, inside the clock domain.
  //
  wire rst_n_sync;
  hydra_rst_sync #(.STAGES(2)) u_rst_sync (
    .clk(clk), .arst_n(rst_n), .scan_mode(1'b0), .scan_rst_n(1'b1),
    .rst_n(rst_n_sync));

  // Four tags: see the header. The chip (mom/hydra_mom_pins.sv) uses eight.
  localparam int unsigned NTAG = 4;

  wire _unused = &{ena, uio_in, ui_in[7:3], 1'b0};

  // =========================================================================
  // REGISTER front end
  // =========================================================================
  wire       spi_cipo, cs_start, cs_end, cs_active, rx_valid, tx_load;
  wire [7:0] rx_byte, tx_byte;
  wire [4:0] rx_index;

  hydra_tt_spi u_spi (
    .clk(clk), .rst_n(rst_n_sync),
    .sck_i(ui_in[0]), .copi_i(ui_in[1]), .csn_i(ui_in[2]), .cipo_o(spi_cipo),
    .cs_start(cs_start), .cs_end(cs_end), .cs_active(cs_active),
    .rx_valid(rx_valid), .rx_byte(rx_byte), .rx_index(rx_index),
    .tx_load(tx_load), .tx_byte(tx_byte)
  );

  wire               r_wd_valid, r_disp_accept, r_comp_valid, r_csr_wr, r_csr_priv;
  wire               r_cal_freeze, r_cal_reset, r_irq, r_disp_sticky;
  wire [WD_W-1:0]    r_wd;
  wire [3:0]         r_comp_tag, r_fence_tag, r_bw, r_eps, r_esh, r_last_tag, r_margin_nib;
  wire [2:0]         r_csr_engine, r_last_engine;
  wire [EPARAM_W-1:0] r_csr_data;

  // =========================================================================
  // MOM
  // =========================================================================
  wire               disp_valid;
  wire  [2:0]        disp_engine;
  wire  [3:0]        disp_tag;
  work_desc_t        disp_wd;
  wire               err_unsupported;
  wire  [7:0]        err_tag;
  wire               err_stale_comp;
  wire  [COST_W-1:0] obs_margin;
  wire  [NTAG-1:0]   obs_tag_busy;
  wire  [15:0]       obs_cal_updates;
  wire               wd_ready;
  wire               fence_busy;

  hydra_tt_regs #(.NTAG(NTAG)) u_regs (
    .clk(clk), .rst_n(rst_n_sync),
    .cs_start(cs_start), .cs_end(cs_end), .rx_valid(rx_valid),
    .rx_byte(rx_byte), .rx_index(rx_index), .tx_load(tx_load), .tx_byte(tx_byte),
    .wd_valid(r_wd_valid), .wd_ready(wd_ready), .wd(r_wd),
    .disp_valid(disp_valid), .disp_accept(r_disp_accept),
    .disp_engine(disp_engine), .disp_tag(disp_tag),
    .comp_valid(r_comp_valid), .comp_tag(r_comp_tag),
    .fence_tag(r_fence_tag), .fence_busy(fence_busy),
    .csr_wr(r_csr_wr), .csr_priv(r_csr_priv), .csr_engine(r_csr_engine),
    .csr_data(r_csr_data), .csr_bw_dma_log2(r_bw), .csr_eps_mem(r_eps),
    .csr_e_shift(r_esh), .csr_cal_freeze(r_cal_freeze), .csr_cal_reset(r_cal_reset),
    .err_unsupported(err_unsupported), .err_tag(err_tag),
    .err_stale_comp(err_stale_comp), .obs_margin(obs_margin),
    .obs_cal_updates(obs_cal_updates), .obs_tag_busy(obs_tag_busy),
    .irq(r_irq), .last_engine(r_last_engine), .disp_sticky(r_disp_sticky),
    .last_tag(r_last_tag), .margin_nib(r_margin_nib)
  );

  mom_top #(.NTAG(NTAG), .QMAX(NTAG)) u_mom (
    .clk(clk), .rst_n(rst_n_sync),
    .wd_valid(r_wd_valid), .wd_ready(wd_ready), .wd(work_desc_t'(r_wd)),
    .disp_valid(disp_valid), .disp_accept(r_disp_accept),
    .disp_engine(disp_engine), .disp_tag(disp_tag), .disp_wd(disp_wd),
    .comp_valid(r_comp_valid), .comp_tag(r_comp_tag),
    .fence_tag(r_fence_tag), .fence_busy(fence_busy),
    .csr_wr(r_csr_wr), .csr_priv(r_csr_priv), .csr_engine(r_csr_engine),
    .csr_data(r_csr_data),
    .csr_bw_dma_log2(r_bw), .csr_eps_mem(r_eps), .csr_e_shift(r_esh),
    .csr_cal_freeze(r_cal_freeze), .csr_cal_reset(r_cal_reset),
    .err_unsupported(err_unsupported), .err_tag(err_tag),
    .err_stale_comp(err_stale_comp),
    .obs_margin(obs_margin), .obs_cal_updates(obs_cal_updates),
    .obs_tag_busy(obs_tag_busy)
  );

  // =========================================================================
  // Pins
  // =========================================================================
  assign uo_out  = { wd_ready, |obs_tag_busy, r_disp_sticky, r_last_engine, r_irq, spi_cipo };
  assign uio_out = { r_margin_nib, r_last_tag };
  assign uio_oe  = 8'hFF;      // every bidirectional is an output

  // The descriptor as dispatched is not observed on this tile (see the
  // header), so synthesis drops the pipeline bits that carried only it.
  wire _unused_spi = &{cs_active, disp_wd, 1'b0};

endmodule

`default_nettype wire
