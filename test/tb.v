/* TinyTapeout cocotb wrapper for tt_um_hydra_mom.
 * Standard shape: instantiate the design, expose the pins, dump waves. */
`default_nettype none
`timescale 1ns/1ps

module tb ();
  initial begin
    $dumpfile("tb.vcd");
    $dumpvars(0, tb);
  end

  reg clk, rst_n, ena;
  reg  [7:0] ui_in, uio_in;
  wire [7:0] uo_out, uio_out, uio_oe;

`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
`endif

  tt_um_hydra_mom user_project (
`ifdef GL_TEST
      .VPWR(VPWR), .VGND(VGND),
`endif
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );
endmodule
