## How it works

This is the dispatch unit from HYDRA-130, a heterogeneous compute SoC. It
decides, in hardware and in three cycles, which of five compute engines should
execute a given unit of work: a scalar CPU, a SIMD unit, a systolic INT8 array,
a number-theoretic transform engine, or a crypto datapath.

Software pushes a 128-bit **work descriptor** describing the job: operation
class, data type, problem dimensions, operand byte count, and hints for latency
and power. Three pipeline stages turn that into an engine index.

**Stage 1 extracts features.** Work volume `W` and arithmetic intensity
`I = W/Q` are computed in the base-2 log domain, so the division becomes a
subtraction of two priority-encoder outputs. About 40 gates instead of a
divider.

**Stage 2 evaluates a roofline cost model**, once per engine in parallel. Each
engine carries peak throughput, setup cost, bandwidth, and energy per operation:

    P_att = min(P_peak, I * BW)
    T     = W/P_att + T_setup + Q/BW_dma + queue_depth
    J     = k*T + lambda*E

Because peak throughput and bandwidth are stored as logarithms, the roofline
minimum is a comparison of small integers and the multiply is a shift.

**Stage 3 takes the argmin** over the five costs, masking out any engine that
cannot handle the descriptor's data type or operation class. Those masks are
correctness gates rather than preferences: dispatching FP32 to an INT8 array
would give wrong answers, not slow ones.

### The part worth taping out

A static cost model is always wrong. The parameters are pre-silicon estimates,
the log-domain arithmetic discards mantissas, and no fixed model anticipates
cache state or a workload nobody characterized.

So the unit **watches what actually happened and corrects itself.** Each
(engine, operation class) pair carries an 8-bit factor `k`, updated from
measured completion times by a sign-LMS rule with a step proportional to `k`:

    err  = T_measured - T_calibrated
    step = max(1, k >> 4)
    k   <- k + sign(err) * step

Sign-LMS rather than a true moving average, because the average needs a 32-bit
divider and the sign does not. The fixed point is the median of measured times,
which is more robust to outliers, and convergence is geometric at 6.25% per
update. Correcting a 3x model error takes about 19 updates. The whole update is
a subtract, a shift, a comparator, and an add.

That is the claim this chip exists to test: **a self-calibrating hardware
dispatch model under 25,000 gates, matching software dispatch decisions with two
orders of magnitude less overhead.**

## How to test

The descriptor is 128 bits and TinyTapeout gives 8 input pins, so it is shifted
in serially.

1. Hold `rst_n` low, then release.
2. Drive `sdi` (ui[0]) with the descriptor MSB first, pulsing `shift` (ui[1])
   once per bit, 128 times.
3. Pulse `go` (ui[2]). Both `go` and `comp` are **edge detected**, so holding
   them high does not re-trigger.
4. Read the result: `engine` on uo[2:0], `dispatched` on uo[3],
   `unsupported` on uo[4], allocated `tag` on uio[3:0].
5. To exercise the calibration loop, wait a chosen number of clocks, then put
   the tag on ui[7:4] and pulse `comp` (ui[3]). Repeat with the same descriptor
   and the same delay; the dispatch decision should shift as `k` converges.

Descriptor field order, MSB first: `op_class[3:0]`, `dtype[2:0]`,
`lat_hint[1:0]`, `pwr_hint[1:0]`, `dim_m[15:0]`, `dim_n[15:0]`, `dim_k[15:0]`,
`bytes[23:0]`, `src_loc[1:0]`, `tag[7:0]`, then 35 reserved bits.

Two descriptors worth trying first, both verified in simulation:

| Descriptor | Expected |
|---|---|
| GEMM, INT8, M=N=K=4, bytes=48 | SIMD (engine 1). The array's 64-cycle weight load dominates at this size. |
| GEMM, INT8, M=N=K=8, bytes=192 | TPU (engine 2). Compute advantage overtakes setup. |

That crossover at M=N=K=8 is the single most interesting thing to confirm in
silicon, because it is where the model's shape claim is actually load-bearing.

Also worth checking: a GEMM over polynomial-ring data type should raise
`unsupported` rather than dispatching, since no engine can perform a GEMM over
ring elements. An earlier version retried such a descriptor forever.

## External hardware

None. An RP2040 on the TinyTapeout demo board drives every pin, and MicroPython
is fast enough: the 128-bit shift at even 100 kHz takes 1.3 ms, and the dispatch
decision it triggers takes 120 ns.

## Verification before tapeout

- 10,000 randomized descriptors cross-checked against an independent Python
  model, stratified so a third land in the roofline crossover band
- Closed-loop calibration test with a synthetic engine returning latencies the
  model cannot know
- Formal proofs on five modules, including an exhaustive proof that the selector
  returns the minimum-cost valid engine


## Timing

Measured with OpenSTA against the sky130 typical corner (25 C, 1.8 V),
register to register: **46.56 ns**, i.e. 21.5 MHz.

`clock_hz` is therefore declared at **20 MHz**, which has margin before any
place-and-route improvement rather than depending on one. Synthesis inserts no
buffers, so its numbers are pessimistic — but the worst fanout in this netlist
is 71, which is modest, so PAR will recover less here than it would on a design
with wide pipeline registers.

The dispatch decision takes three cycles at any clock.

## Area

**110,796 um^2** of sky130 cell area, measured rather than estimated. Against
a 3x4 tile's 260,160 um^2 that is 43% utilisation. Run the harden and read
`design__instance__utilization` from `metrics.json` before ordering: cell area
excludes routing congestion, power straps, and boundary cells.
