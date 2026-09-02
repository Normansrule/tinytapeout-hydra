`default_nettype none
`default_nettype wire
`default_nettype none
module mom_features (
	clk,
	rst_n,
	in_valid,
	in_ready,
	in_wd,
	out_valid,
	out_ready,
	out_wd,
	out_log2_w,
	out_log2_q,
	out_log2_i
);
	reg _sv2v_0;
	input wire clk;
	input wire rst_n;
	input wire in_valid;
	output wire in_ready;
	input wire [127:0] in_wd;
	output reg out_valid;
	input wire out_ready;
	output reg [127:0] out_wd;
	output reg [7:0] out_log2_w;
	output reg [7:0] out_log2_q;
	output reg signed [8:0] out_log2_i;
	assign in_ready = !out_valid || out_ready;
	wire accept = in_valid && in_ready;
	reg [7:0] lg_m;
	reg [7:0] lg_n;
	reg [7:0] lg_k;
	reg [7:0] lg_q;
	reg [7:0] lg_w_c;
	function automatic [7:0] mom_pkg_flog2;
		input reg [31:0] v;
		reg [7:0] r;
		reg [31:0] t;
		begin
			r = 8'd0;
			t = v;
			if (t[31:16] != 16'd0) begin
				r = r + 8'd16;
				t = t >> 16;
			end
			if (t[15:8] != 8'd0) begin
				r = r + 8'd8;
				t = t >> 8;
			end
			if (t[7:4] != 4'd0) begin
				r = r + 8'd4;
				t = t >> 4;
			end
			if (t[3:2] != 2'd0) begin
				r = r + 8'd2;
				t = t >> 2;
			end
			if (t[1] != 1'b0)
				r = r + 8'd1;
			mom_pkg_flog2 = r;
		end
	endfunction
	always @(*) begin
		if (_sv2v_0)
			;
		lg_m = mom_pkg_flog2({16'd0, in_wd[116-:16]});
		lg_n = mom_pkg_flog2({16'd0, in_wd[100-:16]});
		lg_k = mom_pkg_flog2({16'd0, in_wd[84-:16]});
		lg_q = mom_pkg_flog2({8'd0, in_wd[68-:24]});
		(* full_case, parallel_case *)
		case (in_wd[127-:4])
			4'd0, 4'd1, 4'd2: lg_w_c = lg_m;
			4'd3, 4'd4: lg_w_c = ((lg_m + lg_n) + lg_k) + 8'd1;
			4'd5: lg_w_c = (8'd2 + lg_n) + mom_pkg_flog2({24'd0, lg_n});
			4'd6: lg_w_c = (lg_n + mom_pkg_flog2({24'd0, lg_n})) + 8'd1;
			4'd7, 4'd8: lg_w_c = lg_q;
			default: lg_w_c = lg_m;
		endcase
	end
	wire signed [8:0] lg_i_c = $signed({1'b0, lg_w_c}) - $signed({1'b0, lg_q});
	always @(posedge clk or negedge rst_n)
		if (!rst_n) begin
			out_valid <= 1'b0;
			out_wd <= 1'sb0;
			out_log2_w <= 8'd0;
			out_log2_q <= 8'd0;
			out_log2_i <= 9'sd0;
		end
		else if (accept) begin
			out_valid <= 1'b1;
			out_wd <= in_wd;
			out_log2_w <= lg_w_c;
			out_log2_q <= lg_q;
			out_log2_i <= lg_i_c;
		end
		else if (out_ready)
			out_valid <= 1'b0;
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module mom_param_rom (
	clk,
	rst_n,
	wr_en,
	wr_priv,
	wr_engine,
	wr_data,
	params
);
	input wire clk;
	input wire rst_n;
	input wire wr_en;
	input wire wr_priv;
	input wire [2:0] wr_engine;
	localparam [31:0] mom_pkg_EPARAM_W = 43;
	input wire [42:0] wr_data;
	localparam [31:0] mom_pkg_ENG_N = 5;
	output wire [214:0] params;
	localparam [42:0] DEF_CPU = 43'h00001283fff;
	localparam [42:0] DEF_SIMD = 43'h180420a3e3e;
	localparam [42:0] DEF_TPU = 43'h38202810618;
	localparam [42:0] DEF_NTT = 43'h28102044860;
	localparam [42:0] DEF_CRYPTO = 43'h20082020980;
	reg [42:0] row [0:4];
	function automatic [2:0] sv2v_cast_3;
		input reg [2:0] inp;
		sv2v_cast_3 = inp;
	endfunction
	always @(posedge clk or negedge rst_n)
		if (!rst_n) begin
			row[3'd0] <= DEF_CPU;
			row[3'd1] <= DEF_SIMD;
			row[3'd2] <= DEF_TPU;
			row[3'd3] <= DEF_NTT;
			row[3'd4] <= DEF_CRYPTO;
		end
		else if ((wr_en && wr_priv) && (wr_engine < sv2v_cast_3(mom_pkg_ENG_N)))
			row[wr_engine] <= wr_data;
	genvar _gv_e_1;
	function automatic [42:0] sv2v_cast_43;
		input reg [42:0] inp;
		sv2v_cast_43 = inp;
	endfunction
	generate
		for (_gv_e_1 = 0; _gv_e_1 < mom_pkg_ENG_N; _gv_e_1 = _gv_e_1 + 1) begin : g_unpack
			localparam e = _gv_e_1;
			assign params[e * 43+:43] = sv2v_cast_43(row[e]);
		end
	endgenerate
endmodule
`default_nettype wire
`default_nettype none
module mom_cost_engine (
	log2_w,
	bytes_q,
	log2_i,
	dtype,
	op_class,
	lat_hint,
	lambda_sh,
	param,
	k_cal,
	queue_depth,
	engine_busy_full,
	bw_dma_log2,
	eps_mem,
	e_shift,
	cost,
	t_pred,
	valid,
	capable
);
	reg _sv2v_0;
	parameter [2:0] ENGINE_ID = 3'd0;
	input wire [7:0] log2_w;
	input wire [23:0] bytes_q;
	input wire signed [8:0] log2_i;
	input wire [2:0] dtype;
	input wire [3:0] op_class;
	input wire [1:0] lat_hint;
	input wire [3:0] lambda_sh;
	input wire [42:0] param;
	input wire [7:0] k_cal;
	input wire [7:0] queue_depth;
	input wire engine_busy_full;
	input wire [3:0] bw_dma_log2;
	input wire [3:0] eps_mem;
	input wire [3:0] e_shift;
	localparam [31:0] mom_pkg_COST_W = 32;
	output reg [31:0] cost;
	output wire [31:0] t_pred;
	output wire valid;
	output wire capable;
	function automatic mom_pkg_dtype_ok;
		input reg [5:0] mask;
		input reg [2:0] dt;
		mom_pkg_dtype_ok = (mask >> dt) & 1'b1;
	endfunction
	wire dt_supported = mom_pkg_dtype_ok(param[14-:6], dtype);
	function automatic mom_pkg_opc_ok;
		input reg [8:0] mask;
		input reg [3:0] oc;
		mom_pkg_opc_ok = (mask >> oc) & 1'b1;
	endfunction
	wire opc_supported = mom_pkg_opc_ok(param[8-:9], op_class);
	assign capable = dt_supported && opc_supported;
	assign valid = capable && !engine_busy_full;
	wire signed [9:0] bw_bound_s = log2_i + $signed({6'd0, param[26-:4]});
	wire [3:0] bw_bound = (bw_bound_s <= 0 ? 4'd0 : (bw_bound_s >= 15 ? 4'd15 : bw_bound_s[3:0]));
	wire [3:0] lg_p_att = (bw_bound < param[42-:4] ? bw_bound : param[42-:4]);
	wire [3:0] dbg_lg_p_att = lg_p_att;
	wire [7:0] lg_t_comp = (log2_w > {4'd0, lg_p_att} ? log2_w - {4'd0, lg_p_att} : 8'd0);
	wire [4:0] sh_amt = (lg_t_comp > 8'd31 ? 5'd31 : lg_t_comp[4:0]);
	localparam [31:0] mom_pkg_COST_SAT = 32'hffff0000;
	wire [31:0] t_compute = (lg_t_comp > 8'd31 ? mom_pkg_COST_SAT : 32'd1 << sh_amt);
	wire [31:0] t_move = {8'd0, bytes_q} >> bw_dma_log2;
	wire [31:0] t_setup = {20'd0, param[38-:12]};
	wire [1:0] setup_sh = (lat_hint == 2'd3 ? 2'd2 : (lat_hint == 2'd2 ? 2'd1 : 2'd0));
	wire [39:0] t_setup_w = {28'd0, param[38-:12]} << setup_sh;
	wire [39:0] t_sum_w = (({8'd0, t_compute} + t_setup_w) + {8'd0, t_move}) + {32'd0, queue_depth};
	assign t_pred = (t_sum_w > 40'h00ffff0000 ? mom_pkg_COST_SAT : t_sum_w[31:0]);
	reg [4:0] tp_e;
	always @(*) begin
		if (_sv2v_0)
			;
		if (t_pred[31:16] != 16'd0)
			tp_e = 5'd16;
		else if (t_pred[15:8] != 8'd0)
			tp_e = 5'd8;
		else
			tp_e = 5'd0;
	end
	wire [15:0] tp_m = (tp_e == 5'd16 ? t_pred[31:16] : (tp_e == 5'd8 ? t_pred[23:8] : t_pred[15:0]));
	wire [23:0] cal_prod = tp_m * {8'd0, k_cal};
	localparam [31:0] mom_pkg_KCAL_SHIFT = 6;
	function automatic [6:0] sv2v_cast_7;
		input reg [6:0] inp;
		sv2v_cast_7 = inp;
	endfunction
	wire signed [6:0] cal_sh = $signed({2'b00, tp_e}) - $signed(sv2v_cast_7(mom_pkg_KCAL_SHIFT));
	wire [47:0] cal_wide = (cal_sh >= 0 ? {24'd0, cal_prod} << cal_sh[5:0] : {24'd0, cal_prod} >> -cal_sh[5:0]);
	wire [31:0] t_cal = (cal_wide[47:mom_pkg_COST_W] != {16 {1'sb0}} ? mom_pkg_COST_SAT : cal_wide[31:0]);
	wire [5:0] w_sh = (log2_w > 8'd31 ? 6'd31 : {1'b0, log2_w[4:0]});
	wire signed [7:0] net_sh_s = ($signed({2'b00, w_sh}) + $signed({5'b00000, lambda_sh[2:0]})) - $signed({4'b0000, e_shift});
	wire net_pos = ~net_sh_s[7];
	wire [5:0] net_mag = (net_pos ? net_sh_s[5:0] : ~net_sh_s[5:0] + 6'd1);
	wire net_ovf = net_pos && (net_mag > 6'd24);
	wire [31:0] e_ops_sc = ((log2_w > 8'd31) || net_ovf ? mom_pkg_COST_SAT : (net_pos ? {24'd0, param[22-:8]} << net_mag : {24'd0, param[22-:8]} >> net_mag));
	wire [27:0] e_mem_raw = bytes_q * {24'd0, eps_mem};
	wire signed [7:0] mem_sh_s = $signed({5'b00000, lambda_sh[2:0]}) - $signed({4'b0000, e_shift});
	wire mem_pos = ~mem_sh_s[7];
	wire [5:0] mem_mag = (mem_pos ? mem_sh_s[5:0] : ~mem_sh_s[5:0] + 6'd1);
	wire [31:0] e_mem_sc = (mem_pos ? {4'd0, e_mem_raw} << mem_mag : {4'd0, e_mem_raw} >> mem_mag);
	wire [32:0] e_sum_w = (lambda_sh[3] ? {1'b0, e_ops_sc} + {1'b0, e_mem_sc} : 33'd0);
	wire [31:0] e_scaled = (e_sum_w[32] ? mom_pkg_COST_SAT : e_sum_w[31:0]);
	wire [mom_pkg_COST_W:0] j_sum = {1'b0, t_cal} + {1'b0, e_scaled};
	always @(*) begin
		if (_sv2v_0)
			;
		if (!valid)
			cost = {mom_pkg_COST_W {1'b1}};
		else if (j_sum[mom_pkg_COST_W])
			cost = mom_pkg_COST_SAT;
		else
			cost = j_sum[31:0];
	end
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module mom_calibrate (
	clk,
	rst_n,
	freeze,
	reset_factors,
	rd_opclass,
	rd_k,
	upd_valid,
	upd_engine,
	upd_opclass,
	upd_t_measured,
	upd_t_predicted,
	upd_count,
	last_dir
);
	parameter [31:0] ALPHA = 4;
	parameter [7:0] K_MIN = 8'd4;
	parameter [7:0] K_MAX = 8'd255;
	input wire clk;
	input wire rst_n;
	input wire freeze;
	input wire reset_factors;
	input wire [3:0] rd_opclass;
	localparam [31:0] mom_pkg_ENG_N = 5;
	output wire [39:0] rd_k;
	input wire upd_valid;
	input wire [2:0] upd_engine;
	input wire [3:0] upd_opclass;
	localparam [31:0] mom_pkg_COST_W = 32;
	input wire [31:0] upd_t_measured;
	input wire [31:0] upd_t_predicted;
	output reg [15:0] upd_count;
	output reg last_dir;
	localparam [31:0] NOPC = 9;
	reg [7:0] k [0:4][0:8];
	genvar _gv_e_2;
	localparam [7:0] mom_pkg_KCAL_UNITY = 8'd64;
	function automatic [3:0] sv2v_cast_4;
		input reg [3:0] inp;
		sv2v_cast_4 = inp;
	endfunction
	generate
		for (_gv_e_2 = 0; _gv_e_2 < mom_pkg_ENG_N; _gv_e_2 = _gv_e_2 + 1) begin : g_rd
			localparam e = _gv_e_2;
			assign rd_k[e * 8+:8] = (rd_opclass < sv2v_cast_4(NOPC) ? k[e][rd_opclass] : mom_pkg_KCAL_UNITY);
		end
	endgenerate
	function automatic [2:0] sv2v_cast_3;
		input reg [2:0] inp;
		sv2v_cast_3 = inp;
	endfunction
	wire [7:0] k_cur = ((upd_engine < sv2v_cast_3(mom_pkg_ENG_N)) && (upd_opclass < sv2v_cast_4(NOPC)) ? k[upd_engine][upd_opclass] : mom_pkg_KCAL_UNITY);
	wire [39:0] t_cal_wide = upd_t_predicted * {32'd0, k_cur};
	localparam [31:0] mom_pkg_KCAL_SHIFT = 6;
	wire [31:0] t_cal = t_cal_wide[(mom_pkg_COST_W + mom_pkg_KCAL_SHIFT) - 1-:mom_pkg_COST_W];
	wire too_slow = upd_t_measured > t_cal;
	wire too_fast = upd_t_measured < t_cal;
	function automatic [7:0] step_of;
		input reg [7:0] kc;
		reg [7:0] raw;
		begin
			raw = kc >> ALPHA;
			step_of = (raw == 8'd0 ? 8'd1 : raw);
		end
	endfunction
	function automatic [7:0] k_up_of;
		input reg [7:0] kc;
		reg [8:0] w;
		begin
			w = {1'b0, kc} + {1'b0, step_of(kc)};
			k_up_of = (w > {1'b0, K_MAX} ? K_MAX : w[7:0]);
		end
	endfunction
	function automatic [7:0] k_dn_of;
		input reg [7:0] kc;
		reg [8:0] w;
		begin
			w = {1'b0, kc} - {1'b0, step_of(kc)};
			k_dn_of = (w[8] || (w[7:0] < K_MIN) ? K_MIN : w[7:0]);
		end
	endfunction
	wire [7:0] step = step_of(k_cur);
	wire [7:0] k_up = k_up_of(k_cur);
	wire [7:0] k_dn = k_dn_of(k_cur);
	wire [7:0] k_next = (too_slow ? k_up : (too_fast ? k_dn : k_cur));
	wire do_update = (upd_valid && !freeze) && (upd_t_predicted != {32 {1'sb0}});
	always @(posedge clk or negedge rst_n)
		if (!rst_n) begin
			begin : sv2v_autoblock_1
				reg signed [31:0] e;
				for (e = 0; e < mom_pkg_ENG_N; e = e + 1)
					begin : sv2v_autoblock_2
						reg signed [31:0] c;
						for (c = 0; c < NOPC; c = c + 1)
							k[e][c] <= mom_pkg_KCAL_UNITY;
					end
			end
			upd_count <= 16'd0;
			last_dir <= 1'b0;
		end
		else if (reset_factors) begin
			begin : sv2v_autoblock_3
				reg signed [31:0] e;
				for (e = 0; e < mom_pkg_ENG_N; e = e + 1)
					begin : sv2v_autoblock_4
						reg signed [31:0] c;
						for (c = 0; c < NOPC; c = c + 1)
							k[e][c] <= mom_pkg_KCAL_UNITY;
					end
			end
			upd_count <= 16'd0;
		end
		else if (do_update) begin
			k[upd_engine][upd_opclass] <= k_next;
			upd_count <= upd_count + 16'd1;
			last_dir <= too_slow;
		end
endmodule
`default_nettype wire
`default_nettype none
module mom_select (
	cost,
	valid,
	capable,
	sel_engine,
	sel_cost,
	any_valid,
	any_capable,
	sel_margin
);
	reg _sv2v_0;
	parameter [0:0] WANT_MARGIN = 1;
	localparam [31:0] mom_pkg_COST_W = 32;
	localparam [31:0] mom_pkg_ENG_N = 5;
	input wire [(mom_pkg_ENG_N * mom_pkg_COST_W) - 1:0] cost;
	input wire [4:0] valid;
	input wire [4:0] capable;
	output reg [2:0] sel_engine;
	output reg [31:0] sel_cost;
	output reg any_valid;
	output reg any_capable;
	output reg [31:0] sel_margin;
	localparam [31:0] PW = 36;
	wire [35:0] lane [0:4];
	genvar _gv_e_3;
	function automatic signed [2:0] sv2v_cast_3_signed;
		input reg signed [2:0] inp;
		sv2v_cast_3_signed = inp;
	endfunction
	generate
		for (_gv_e_3 = 0; _gv_e_3 < mom_pkg_ENG_N; _gv_e_3 = _gv_e_3 + 1) begin : g_pack
			localparam e = _gv_e_3;
			assign lane[e] = {~valid[e], cost[e * mom_pkg_COST_W+:mom_pkg_COST_W], sv2v_cast_3_signed(e)};
		end
	endgenerate
	function automatic [35:0] pick;
		input reg [35:0] a;
		input reg [35:0] b;
		pick = (a[35:3] <= b[35:3] ? a : b);
	endfunction
	wire [35:0] l1_a = pick(lane[0], lane[1]);
	wire [35:0] l1_b = pick(lane[2], lane[3]);
	wire [35:0] l2 = pick(l1_a, l1_b);
	wire [35:0] best = pick(l2, lane[4]);
	wire [35:0] snd;
	generate
		if (WANT_MARGIN) begin : g_margin
			wire [35:0] lane2 [0:4];
			genvar _gv_e_4;
			for (_gv_e_4 = 0; _gv_e_4 < mom_pkg_ENG_N; _gv_e_4 = _gv_e_4 + 1) begin : g_pack2
				localparam e = _gv_e_4;
				assign lane2[e] = (sv2v_cast_3_signed(e) == best[2:0] ? {1'b1, cost[e * mom_pkg_COST_W+:mom_pkg_COST_W], sv2v_cast_3_signed(e)} : lane[e]);
			end
			wire [35:0] m1_a = pick(lane2[0], lane2[1]);
			wire [35:0] m1_b = pick(lane2[2], lane2[3]);
			wire [35:0] m2 = pick(m1_a, m1_b);
			assign snd = pick(m2, lane2[4]);
		end
		else begin : g_no_margin
			assign snd = {1'b1, {mom_pkg_COST_W {1'b0}}, 3'd0};
		end
	endgenerate
	always @(*) begin
		if (_sv2v_0)
			;
		any_valid = |valid;
		any_capable = |capable;
		sel_engine = best[2:0];
		sel_cost = best[34:3];
		sel_margin = (snd[35] || !any_valid ? {32 {1'sb0}} : (snd[34:3] >= best[34:3] ? snd[34:3] - best[34:3] : {32 {1'sb0}}));
	end
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module mom_scoreboard (
	clk,
	rst_n,
	disp_valid,
	disp_ready,
	disp_engine,
	disp_opclass,
	disp_t_pred,
	disp_tag,
	comp_valid,
	comp_tag,
	cal_valid,
	cal_engine,
	cal_opclass,
	cal_t_measured,
	cal_t_predicted,
	queue_depth,
	engine_full,
	fence_tag,
	fence_busy,
	err_stale_comp,
	tag_busy_vec
);
	reg _sv2v_0;
	parameter [31:0] NTAG = 16;
	parameter [31:0] QMAX = 8;
	input wire clk;
	input wire rst_n;
	input wire disp_valid;
	output wire disp_ready;
	input wire [2:0] disp_engine;
	input wire [3:0] disp_opclass;
	localparam [31:0] mom_pkg_COST_W = 32;
	input wire [31:0] disp_t_pred;
	output wire [3:0] disp_tag;
	input wire comp_valid;
	input wire [3:0] comp_tag;
	output reg cal_valid;
	output reg [2:0] cal_engine;
	output reg [3:0] cal_opclass;
	output reg [31:0] cal_t_measured;
	output reg [31:0] cal_t_predicted;
	localparam [31:0] mom_pkg_ENG_N = 5;
	output reg [39:0] queue_depth;
	output wire [4:0] engine_full;
	input wire [3:0] fence_tag;
	output wire fence_busy;
	output reg err_stale_comp;
	output wire [NTAG - 1:0] tag_busy_vec;
	reg [31:0] now;
	always @(posedge clk or negedge rst_n)
		if (!rst_n)
			now <= 1'sb0;
		else
			now <= now + 32'd1;
	reg busy [0:NTAG - 1];
	reg [2:0] t_eng [0:NTAG - 1];
	reg [3:0] t_opc [0:NTAG - 1];
	reg [31:0] t_start [0:NTAG - 1];
	reg [31:0] t_pred [0:NTAG - 1];
	genvar _gv_t_1;
	generate
		for (_gv_t_1 = 0; _gv_t_1 < NTAG; _gv_t_1 = _gv_t_1 + 1) begin : g_busyvec
			localparam t = _gv_t_1;
			assign tag_busy_vec[t] = busy[t];
		end
	endgenerate
	reg [3:0] free_tag;
	reg have_free;
	function automatic signed [3:0] sv2v_cast_4_signed;
		input reg signed [3:0] inp;
		sv2v_cast_4_signed = inp;
	endfunction
	always @(*) begin
		if (_sv2v_0)
			;
		free_tag = 4'd0;
		have_free = 1'b0;
		begin : sv2v_autoblock_1
			reg signed [31:0] t;
			for (t = NTAG - 1; t >= 0; t = t - 1)
				if (!busy[t]) begin
					free_tag = sv2v_cast_4_signed(t);
					have_free = 1'b1;
				end
		end
	end
	function automatic [2:0] sv2v_cast_3;
		input reg [2:0] inp;
		sv2v_cast_3 = inp;
	endfunction
	wire disp_engine_ok = disp_engine < sv2v_cast_3(mom_pkg_ENG_N);
	wire comp_tag_ok = {28'd0, comp_tag} < NTAG;
	wire engine_has_room = disp_engine_ok && !engine_full[disp_engine];
	assign disp_ready = have_free && engine_has_room;
	assign disp_tag = free_tag;
	wire do_disp = disp_valid && disp_ready;
	wire do_comp = (comp_valid && comp_tag_ok) && busy[comp_tag];
	wire stale_comp = comp_valid && (!comp_tag_ok || !busy[comp_tag]);
	always @(posedge clk or negedge rst_n)
		if (!rst_n)
			err_stale_comp <= 1'b0;
		else
			err_stale_comp <= stale_comp;
	genvar _gv_e_5;
	function automatic signed [2:0] sv2v_cast_3_signed;
		input reg signed [2:0] inp;
		sv2v_cast_3_signed = inp;
	endfunction
	function automatic [7:0] sv2v_cast_8;
		input reg [7:0] inp;
		sv2v_cast_8 = inp;
	endfunction
	generate
		for (_gv_e_5 = 0; _gv_e_5 < mom_pkg_ENG_N; _gv_e_5 = _gv_e_5 + 1) begin : g_queue
			localparam e = _gv_e_5;
			wire inc = do_disp && (disp_engine == sv2v_cast_3_signed(e));
			wire dec = do_comp && (t_eng[comp_tag] == sv2v_cast_3_signed(e));
			always @(posedge clk or negedge rst_n)
				if (!rst_n)
					queue_depth[e * 8+:8] <= 8'd0;
				else if (inc && !dec)
					queue_depth[e * 8+:8] <= queue_depth[e * 8+:8] + 8'd1;
				else if ((dec && !inc) && (queue_depth[e * 8+:8] != 8'd0))
					queue_depth[e * 8+:8] <= queue_depth[e * 8+:8] - 8'd1;
			assign engine_full[e] = queue_depth[e * 8+:8] >= sv2v_cast_8(QMAX);
		end
	endgenerate
	always @(posedge clk or negedge rst_n)
		if (!rst_n) begin : sv2v_autoblock_2
			reg signed [31:0] t;
			for (t = 0; t < NTAG; t = t + 1)
				begin
					busy[t] <= 1'b0;
					t_eng[t] <= 3'd0;
					t_opc[t] <= 4'd0;
					t_start[t] <= 1'sb0;
					t_pred[t] <= 1'sb0;
				end
		end
		else begin
			if (do_disp) begin
				busy[free_tag] <= 1'b1;
				t_eng[free_tag] <= disp_engine;
				t_opc[free_tag] <= disp_opclass;
				t_start[free_tag] <= now;
				t_pred[free_tag] <= disp_t_pred;
			end
			if (do_comp)
				busy[comp_tag] <= 1'b0;
		end
	always @(posedge clk or negedge rst_n)
		if (!rst_n)
			cal_valid <= 1'b0;
		else begin
			cal_valid <= do_comp;
			cal_engine <= t_eng[comp_tag];
			cal_opclass <= t_opc[comp_tag];
			cal_t_measured <= now - t_start[comp_tag];
			cal_t_predicted <= t_pred[comp_tag];
		end
	assign fence_busy = busy[fence_tag];
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module mom_top (
	clk,
	rst_n,
	wd_valid,
	wd_ready,
	wd,
	disp_valid,
	disp_accept,
	disp_engine,
	disp_tag,
	disp_wd,
	comp_valid,
	comp_tag,
	fence_tag,
	fence_busy,
	csr_wr,
	csr_priv,
	csr_engine,
	csr_data,
	csr_bw_dma_log2,
	csr_eps_mem,
	csr_e_shift,
	csr_cal_freeze,
	csr_cal_reset,
	err_unsupported,
	err_tag,
	err_stale_comp,
	obs_margin,
	obs_cal_updates,
	obs_tag_busy
);
	parameter [31:0] NTAG = 16;
	parameter [31:0] QMAX = 8;
	input wire clk;
	input wire rst_n;
	input wire wd_valid;
	output wire wd_ready;
	input wire [127:0] wd;
	output wire disp_valid;
	input wire disp_accept;
	output wire [2:0] disp_engine;
	output wire [3:0] disp_tag;
	output wire [127:0] disp_wd;
	input wire comp_valid;
	input wire [3:0] comp_tag;
	input wire [3:0] fence_tag;
	output wire fence_busy;
	input wire csr_wr;
	input wire csr_priv;
	input wire [2:0] csr_engine;
	localparam [31:0] mom_pkg_EPARAM_W = 43;
	input wire [42:0] csr_data;
	input wire [3:0] csr_bw_dma_log2;
	input wire [3:0] csr_eps_mem;
	input wire [3:0] csr_e_shift;
	input wire csr_cal_freeze;
	input wire csr_cal_reset;
	output reg err_unsupported;
	output reg [7:0] err_tag;
	output wire err_stale_comp;
	localparam [31:0] mom_pkg_COST_W = 32;
	output wire [31:0] obs_margin;
	output wire [15:0] obs_cal_updates;
	output wire [NTAG - 1:0] obs_tag_busy;
	wire f_valid;
	wire f_ready;
	wire [127:0] f_wd;
	wire [7:0] f_lg_w;
	wire [7:0] f_lg_q;
	wire signed [8:0] f_lg_i;
	mom_features u_feat(
		.clk(clk),
		.rst_n(rst_n),
		.in_valid(wd_valid),
		.in_ready(wd_ready),
		.in_wd(wd),
		.out_valid(f_valid),
		.out_ready(f_ready),
		.out_wd(f_wd),
		.out_log2_w(f_lg_w),
		.out_log2_q(f_lg_q),
		.out_log2_i(f_lg_i)
	);
	localparam [31:0] mom_pkg_ENG_N = 5;
	wire [214:0] params;
	mom_param_rom u_prom(
		.clk(clk),
		.rst_n(rst_n),
		.wr_en(csr_wr),
		.wr_priv(csr_priv),
		.wr_engine(csr_engine),
		.wr_data(csr_data),
		.params(params)
	);
	wire [39:0] queue_depth;
	wire [4:0] engine_full;
	wire cal_valid;
	wire [2:0] cal_engine;
	wire [3:0] cal_opclass;
	wire [31:0] cal_t_meas;
	wire [31:0] cal_t_pred;
	wire [39:0] k_cal;
	mom_calibrate u_cal(
		.clk(clk),
		.rst_n(rst_n),
		.freeze(csr_cal_freeze),
		.reset_factors(csr_cal_reset),
		.rd_opclass(f_wd[127-:4]),
		.rd_k(k_cal),
		.upd_valid(cal_valid),
		.upd_engine(cal_engine),
		.upd_opclass(cal_opclass),
		.upd_t_measured(cal_t_meas),
		.upd_t_predicted(cal_t_pred),
		.upd_count(obs_cal_updates),
		.last_dir()
	);
	wire [(mom_pkg_ENG_N * mom_pkg_COST_W) - 1:0] cost;
	wire [(mom_pkg_ENG_N * mom_pkg_COST_W) - 1:0] t_pred;
	wire [4:0] cvalid;
	genvar _gv_e_6;
	wire [4:0] ccapable;
	function automatic [3:0] mom_pkg_lambda_sh_of;
		input reg [1:0] h;
		case (h)
			2'd0: mom_pkg_lambda_sh_of = 4'b0000;
			2'd1: mom_pkg_lambda_sh_of = 4'b1000;
			2'd2: mom_pkg_lambda_sh_of = 4'b1010;
			2'd3: mom_pkg_lambda_sh_of = 4'b1100;
			default: mom_pkg_lambda_sh_of = 4'b1000;
		endcase
	endfunction
	function automatic [2:0] sv2v_cast_3;
		input reg [2:0] inp;
		sv2v_cast_3 = inp;
	endfunction
	generate
		for (_gv_e_6 = 0; _gv_e_6 < mom_pkg_ENG_N; _gv_e_6 = _gv_e_6 + 1) begin : g_cost
			localparam e = _gv_e_6;
			mom_cost_engine #(.ENGINE_ID(sv2v_cast_3(e))) u_ce(
				.log2_w(f_lg_w),
				.bytes_q(f_wd[68-:24]),
				.log2_i(f_lg_i),
				.dtype(f_wd[123-:3]),
				.op_class(f_wd[127-:4]),
				.lat_hint(f_wd[120-:2]),
				.lambda_sh(mom_pkg_lambda_sh_of(f_wd[118-:2])),
				.param(params[e * 43+:43]),
				.k_cal(k_cal[e * 8+:8]),
				.queue_depth(queue_depth[e * 8+:8]),
				.engine_busy_full(engine_full[e]),
				.bw_dma_log2(csr_bw_dma_log2),
				.eps_mem(csr_eps_mem),
				.e_shift(csr_e_shift),
				.cost(cost[e * mom_pkg_COST_W+:mom_pkg_COST_W]),
				.t_pred(t_pred[e * mom_pkg_COST_W+:mom_pkg_COST_W]),
				.valid(cvalid[e]),
				.capable(ccapable[e])
			);
		end
	endgenerate
	wire [2:0] sel_eng;
	wire [31:0] sel_cost;
	wire sel_ok;
	wire sel_capable;
	mom_select u_sel(
		.cost(cost),
		.valid(cvalid),
		.capable(ccapable),
		.sel_engine(sel_eng),
		.sel_cost(sel_cost),
		.any_valid(sel_ok),
		.any_capable(sel_capable),
		.sel_margin(obs_margin)
	);
	wire unsupported = f_valid && !sel_capable;
	always @(posedge clk or negedge rst_n)
		if (!rst_n) begin
			err_unsupported <= 1'b0;
			err_tag <= 8'd0;
		end
		else begin
			err_unsupported <= unsupported;
			if (unsupported)
				err_tag <= f_wd[42-:8];
		end
	wire sb_ready;
	mom_scoreboard #(
		.NTAG(NTAG),
		.QMAX(QMAX)
	) u_sb(
		.clk(clk),
		.rst_n(rst_n),
		.disp_valid((f_valid && sel_ok) && disp_accept),
		.disp_ready(sb_ready),
		.disp_engine(sel_eng),
		.disp_opclass(f_wd[127-:4]),
		.disp_t_pred(t_pred[sel_eng * mom_pkg_COST_W+:mom_pkg_COST_W]),
		.disp_tag(disp_tag),
		.comp_valid(comp_valid),
		.comp_tag(comp_tag),
		.cal_valid(cal_valid),
		.cal_engine(cal_engine),
		.cal_opclass(cal_opclass),
		.cal_t_measured(cal_t_meas),
		.cal_t_predicted(cal_t_pred),
		.queue_depth(queue_depth),
		.engine_full(engine_full),
		.fence_tag(fence_tag),
		.fence_busy(fence_busy),
		.err_stale_comp(err_stale_comp),
		.tag_busy_vec(obs_tag_busy)
	);
	assign disp_valid = (f_valid && sel_ok) && sb_ready;
	assign disp_engine = sel_eng;
	assign disp_wd = f_wd;
	assign f_ready = (disp_valid && disp_accept) || unsupported;
endmodule
`default_nettype wire
`default_nettype none
module tt_um_hydra_mom (
	ui_in,
	uo_out,
	uio_in,
	uio_out,
	uio_oe,
	ena,
	clk,
	rst_n
);
	input wire [7:0] ui_in;
	output wire [7:0] uo_out;
	input wire [7:0] uio_in;
	output wire [7:0] uio_out;
	output wire [7:0] uio_oe;
	input wire ena;
	input wire clk;
	input wire rst_n;
	wire _unused = &{ena, uio_in, 1'b0};
	wire sdi = ui_in[0];
	wire shift = ui_in[1];
	wire go = ui_in[2];
	wire comp = ui_in[3];
	wire [3:0] comp_tag_in = ui_in[7:4];
	localparam [31:0] mom_pkg_WD_W = 128;
	reg [127:0] sr;
	always @(posedge clk or negedge rst_n)
		if (!rst_n)
			sr <= 1'sb0;
		else if (shift)
			sr <= {sr[126:0], sdi};
	reg go_q;
	always @(posedge clk or negedge rst_n)
		if (!rst_n)
			go_q <= 1'b0;
		else
			go_q <= go;
	wire go_pulse = go & ~go_q;
	reg comp_q;
	always @(posedge clk or negedge rst_n)
		if (!rst_n)
			comp_q <= 1'b0;
		else
			comp_q <= comp;
	wire comp_pulse = comp & ~comp_q;
	wire disp_valid;
	wire [2:0] disp_engine;
	wire [3:0] disp_tag;
	wire [127:0] disp_wd;
	wire err_unsupported;
	wire [7:0] err_tag;
	wire err_stale_comp;
	localparam [31:0] mom_pkg_COST_W = 32;
	wire [31:0] obs_margin;
	wire [7:0] obs_tag_busy;
	wire [15:0] obs_cal_updates;
	wire wd_ready;
	localparam [31:0] mom_pkg_EPARAM_W = 43;
	function automatic [127:0] sv2v_cast_128;
		input reg [127:0] inp;
		sv2v_cast_128 = inp;
	endfunction
	mom_top #(
		.NTAG(8),
		.QMAX(4)
	) u_mom(
		.clk(clk),
		.rst_n(rst_n),
		.wd_valid(go_pulse),
		.wd_ready(wd_ready),
		.wd(sv2v_cast_128(sr)),
		.disp_valid(disp_valid),
		.disp_accept(1'b1),
		.disp_engine(disp_engine),
		.disp_tag(disp_tag),
		.disp_wd(disp_wd),
		.comp_valid(comp_pulse),
		.comp_tag(comp_tag_in),
		.fence_tag(4'd0),
		.fence_busy(),
		.csr_wr(1'b0),
		.csr_priv(1'b0),
		.csr_engine(3'd0),
		.csr_data({mom_pkg_EPARAM_W {1'b0}}),
		.csr_bw_dma_log2(4'd4),
		.csr_eps_mem(4'd12),
		.csr_e_shift(4'd8),
		.csr_cal_freeze(1'b0),
		.csr_cal_reset(1'b0),
		.err_unsupported(err_unsupported),
		.err_tag(err_tag),
		.err_stale_comp(err_stale_comp),
		.obs_margin(obs_margin),
		.obs_cal_updates(obs_cal_updates),
		.obs_tag_busy(obs_tag_busy)
	);
	reg [2:0] r_engine;
	reg [3:0] r_tag;
	reg r_disp;
	reg r_unsupp;
	reg [3:0] r_margin;
	wire [3:0] margin_nib = (obs_margin[31:12] != {20 {1'sb0}} ? 4'hf : obs_margin[15:12]);
	always @(posedge clk or negedge rst_n)
		if (!rst_n) begin
			r_engine <= 3'd0;
			r_tag <= 4'd0;
			r_disp <= 1'b0;
			r_unsupp <= 1'b0;
			r_margin <= 4'd0;
		end
		else begin
			if (go_pulse) begin
				r_disp <= 1'b0;
				r_unsupp <= 1'b0;
			end
			if (disp_valid) begin
				r_engine <= disp_engine;
				r_tag <= disp_tag;
				r_margin <= margin_nib;
				r_disp <= 1'b1;
			end
			if (err_unsupported)
				r_unsupp <= 1'b1;
		end
	reg r_stale;
	always @(posedge clk or negedge rst_n)
		if (!rst_n)
			r_stale <= 1'b0;
		else if (err_stale_comp)
			r_stale <= 1'b1;
	assign uo_out = {wd_ready, |obs_tag_busy, r_stale, r_unsupp, r_disp, r_engine};
	assign uio_out = {r_margin, r_tag};
	assign uio_oe = 8'hff;
endmodule
`default_nettype wire
