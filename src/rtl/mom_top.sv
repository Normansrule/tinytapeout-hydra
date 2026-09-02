/*
 * mom_top.sv
 *
 * HYDRA-130 - Mathematical Operation MUX, top level
 * Copyright (c) 2026 Aleksander J. Norman
 * SPDX-License-Identifier: Apache-2.0
 *
 * ===========================================================================
 * PIPELINE
 * ===========================================================================
 *   cycle 1   mom_features     W, Q, log2(I)
 *   cycle 2   mom_cost_engine  five costs in parallel, one per engine
 *   cycle 3   mom_select       argmin, then allocate a tag and dispatch
 *
 * Three cycles from descriptor to dispatch. Software doing the same decision
 * costs 200 to 400 cycles: read the sizes, branch on op class, estimate, pick.
 * That is the two-orders-of-magnitude claim, and it is the reason this exists
 * in hardware at all.
 *
 * ===========================================================================
 * THE FEEDBACK LOOP
 * ===========================================================================
 *   dispatch --> engine runs --> completion --> scoreboard measures elapsed
 *                                                    |
 *                                          calibrate adjusts k
 *                                                    |
 *                                          cost engine reads k  <-- closes here
 *
 * The loop is entirely in hardware and needs no software involvement. That is
 * what makes the model self-tuning on workloads nobody characterized.
 * ===========================================================================
 */

`default_nettype none

module mom_top
  import mom_pkg::*;
#(
  parameter int unsigned NTAG = 16,
  parameter int unsigned QMAX = 8
) (
  input  wire                clk,
  input  wire                rst_n,

  // ---- work descriptor in --------------------------------------------------
  input  wire                wd_valid,
  output wire                wd_ready,
  input  wire  work_desc_t   wd,

  // ---- dispatch out, to the engine crossbar --------------------------------
  output logic               disp_valid,
  input  wire                disp_accept,
  output logic [2:0]         disp_engine,
  output logic [3:0]         disp_tag,
  output work_desc_t         disp_wd,

  // ---- completion in -------------------------------------------------------
  input  wire                comp_valid,
  input  wire  [3:0]         comp_tag,

  // ---- fence ---------------------------------------------------------------
  input  wire  [3:0]         fence_tag,
  output wire                fence_busy,

  // ---- CSR -----------------------------------------------------------------
  input  wire                csr_wr,
  input  wire                csr_priv,
  input  wire  [2:0]         csr_engine,
  input  wire  [EPARAM_W-1:0] csr_data,
  input  wire  [3:0]         csr_bw_dma_log2,
  input  wire  [3:0]         csr_eps_mem,
  input  wire  [3:0]         csr_e_shift,
  input  wire                csr_cal_freeze,
  input  wire                csr_cal_reset,

  // ---- observability, mapped into the debug CSR block ----------------------
  // ---- error path ----------------------------------------------------------
  // Pulses for one cycle when a descriptor is discarded because no engine has
  // the capability to execute it. The descriptor's tag field is echoed so
  // software can match the error to the request. Without this the pipeline
  // would retry an unsatisfiable descriptor forever.
  output logic               err_unsupported,
  output logic [7:0]         err_tag,
  output wire                err_stale_comp,

  output wire  [COST_W-1:0]  obs_margin,
  output wire  [15:0]        obs_cal_updates,
  output wire  [NTAG-1:0]    obs_tag_busy
);

  // ===========================================================================
  // Stage 1: feature extraction
  // ===========================================================================
  logic              f_valid;
  logic              f_ready;
  work_desc_t        f_wd;
  logic [7:0]        f_lg_w, f_lg_q;
  logic signed [8:0] f_lg_i;

  mom_features u_feat (
    .clk(clk), .rst_n(rst_n),
    .in_valid(wd_valid), .in_ready(wd_ready), .in_wd(wd),
    .out_valid(f_valid), .out_ready(f_ready), .out_wd(f_wd),
    .out_log2_w(f_lg_w), .out_log2_q(f_lg_q), .out_log2_i(f_lg_i)
  );

  // ===========================================================================
  // Parameters, calibration, scoreboard
  // ===========================================================================
  eng_param_t [ENG_N-1:0] params;

  mom_param_rom u_prom (
    .clk(clk), .rst_n(rst_n),
    .wr_en(csr_wr), .wr_priv(csr_priv),
    .wr_engine(csr_engine), .wr_data(csr_data),
    .params(params)
  );

  logic [ENG_N-1:0][7:0] queue_depth;
  logic [ENG_N-1:0]      engine_full;
  logic              cal_valid;
  logic [2:0]        cal_engine;
  opclass_e          cal_opclass;
  logic [COST_W-1:0] cal_t_meas, cal_t_pred;

  // One shared calibration array with ENG_N parallel read ports. See the
  // header of mom_calibrate.sv for why this is not five instances.
  wire [ENG_N-1:0][7:0] k_cal;

  mom_calibrate u_cal (
    .clk(clk), .rst_n(rst_n),
    .freeze(csr_cal_freeze), .reset_factors(csr_cal_reset),
    .rd_opclass(f_wd.op_class), .rd_k(k_cal),
    .upd_valid(cal_valid), .upd_engine(cal_engine),
    .upd_opclass(cal_opclass),
    .upd_t_measured(cal_t_meas), .upd_t_predicted(cal_t_pred),
    .upd_count(obs_cal_updates), .last_dir()
  );

  // ===========================================================================
  // Stage 2: five cost engines in parallel
  // ===========================================================================
  logic [ENG_N-1:0][COST_W-1:0] cost;
  logic [ENG_N-1:0][COST_W-1:0] t_pred;
  logic [ENG_N-1:0]             cvalid;

  for (genvar e = 0; e < ENG_N; e++) begin : g_cost
    mom_cost_engine #(.ENGINE_ID(engine_e'(e))) u_ce (
      .log2_w(f_lg_w), .bytes_q(f_wd.bytes), .log2_i(f_lg_i),
      .dtype(f_wd.dtype), .op_class(f_wd.op_class), .lat_hint(f_wd.lat_hint),
      .lambda_sh(lambda_sh_of(f_wd.pwr_hint)),
      .param(params[e]), .k_cal(k_cal[e]),
      .queue_depth(queue_depth[e]), .engine_busy_full(engine_full[e]),
      .bw_dma_log2(csr_bw_dma_log2), .eps_mem(csr_eps_mem),
      .e_shift(csr_e_shift),
      .cost(cost[e]), .t_pred(t_pred[e]), .valid(cvalid[e]),
      .capable(ccapable[e])
    );
  end

  // ===========================================================================
  // Stage 3: argmin
  // ===========================================================================
  logic [2:0]        sel_eng;
  logic [COST_W-1:0] sel_cost;
  logic              sel_ok;
  logic              sel_capable;
  logic [ENG_N-1:0]  ccapable;

  mom_select u_sel (
    .cost(cost), .valid(cvalid), .capable(ccapable),
    .sel_engine(sel_eng), .sel_cost(sel_cost),
    .any_valid(sel_ok), .any_capable(sel_capable),
    .sel_margin(obs_margin)
  );

  // An unsatisfiable descriptor is consumed and reported, never retried.
  wire unsupported = f_valid && !sel_capable;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      err_unsupported <= 1'b0;
      err_tag         <= 8'd0;
    end else begin
      err_unsupported <= unsupported;
      if (unsupported) err_tag <= f_wd.tag;
    end
  end

  // ===========================================================================
  // Tag allocation and dispatch handshake
  // ===========================================================================
  wire sb_ready;

  mom_scoreboard #(.NTAG(NTAG), .QMAX(QMAX)) u_sb (
    .clk(clk), .rst_n(rst_n),
    .disp_valid(f_valid && sel_ok && disp_accept),
    .disp_ready(sb_ready),
    .disp_engine(sel_eng), .disp_opclass(f_wd.op_class),
    .disp_t_pred(t_pred[sel_eng]), .disp_tag(disp_tag),
    .comp_valid(comp_valid), .comp_tag(comp_tag),
    .cal_valid(cal_valid), .cal_engine(cal_engine),
    .cal_opclass(cal_opclass),
    .cal_t_measured(cal_t_meas), .cal_t_predicted(cal_t_pred),
    .queue_depth(queue_depth), .engine_full(engine_full),
    .fence_tag(fence_tag), .fence_busy(fence_busy),
    .err_stale_comp(err_stale_comp),
    .tag_busy_vec(obs_tag_busy)
  );

  // A descriptor advances only when an engine was selectable AND a tag was
  // available AND the crossbar accepted. Any of the three failing leaves it in
  // stage 1 to retry, which is why there is no separate stall FSM.
  assign disp_valid = f_valid && sel_ok && sb_ready;
  assign disp_engine = sel_eng;
  assign disp_wd     = f_wd;
  // Drain on a successful dispatch OR on an unsupported descriptor. The second
  // term is what breaks the livelock.
  assign f_ready     = (disp_valid && disp_accept) || unsupported;

endmodule

`default_nettype wire
