## How it works

**A research tile.** This is the dispatch unit from HYDRA-130, a heterogeneous
compute SoC, cut down to the part a paper needs silicon evidence for: the
cost model, its online calibration, and the register map that observes and
retunes them. The full dispatcher, with the engines it schedules, is in the
HYDRA-130 chip ([hydra-skywater130](https://github.com/Normansrule/hydra-skywater130)).

It
decides, in hardware and in about thirteen cycles, which of five compute engines should
execute a given unit of work: a scalar CPU, a SIMD unit, a systolic INT8 array,
a number-theoretic transform engine, or a crypto datapath.

Software pushes a 128-bit **work descriptor** describing the job: operation
class, data type, problem dimensions, operand byte count, and hints for latency
and power. Three pipeline stages turn that into an engine index.

**Stage 1 extracts features.** Work volume `W` and arithmetic intensity
`I = W/Q` are computed in the base-2 log domain, so the division becomes a
subtraction of two priority-encoder outputs. About 40 gates instead of a
divider.

**Stage 2 evaluates a roofline cost model** for each engine in turn, on one
shared cost engine, two cycles per engine. Each
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

### Reset

`rst_n` is asserted immediately but **released two clock cycles later**,
through a synchroniser. Every internal flip-flop therefore leaves reset on the
same edge, and the reset's timing checks start inside the clock domain rather
than at a pin. Allow three clock cycles after releasing `rst_n` before the
first SPI frame.

## How to test

Everything goes through an SPI register map: mode 0, most significant bit
first, SCK at most clk/8 (1.9 MHz at the 15.15 MHz clock). A frame is one
command byte, `{rw, addr[6:0]}` with `rw = 1` for a read, then the data bytes.
While the command byte shifts in, CIPO returns the upper byte of STATUS. A
write takes effect when CSn rises, and only if exactly the register's length
arrived; anything else changes nothing and sets FRAME_ERR.

| addr | register | bytes | |
|---|---|---|---|
| 0x00 | ID | 4 | reads `0x48594D33`, "HYM3" |
| 0x01 | WD | 16 | the descriptor |
| 0x02 | CTRL | 1 | HOLD, CAL_FREEZE, CAL_RESET, PARAM_LOCK |
| 0x03 | ACTION | 1 | bit 0 GO, bit 1 CLEAR_STICKY |
| 0x04 | COMP | 1 | complete this tag |
| 0x05 | STATUS | 2 | ready, busy, pending, WD_OK, dispatched, unsupported, stale, ... |
| 0x06 | RESULT | 6 | engine, tag, the full 32-bit margin, error tag |
| 0x08 | CALUPD | 2 | calibration updates so far |
| 0x09 | BUSY | 2 | which of the four tags are in flight |
| 0x0A | FENCE | 1 | is this tag still busy? |
| 0x0B | PARAM | 6 | rewrite one engine's cost-model row |
| 0x0C | GLOBAL | 2 | DMA bandwidth, memory energy, energy weight |
| 0x0D | INFO | 1 | number of tags: 4 |

`src/rtl/hydra_tt_regs.sv` documents every bit.

1. Hold `rst_n` low, then release. Keep CSn (ui[2]) high.
2. Write the descriptor: `0x01` then 16 bytes, most significant first.
3. Write `0x03, 0x01` (GO).
4. Read RESULT (`0x86` then 6 bytes): engine in bits 47:45, tag in 44:41.
   The pins show the same engine on uo[4:2] and the tag on uio[3:0].
5. To exercise calibration, wait a chosen number of clocks and write the tag
   to COMP (`0x04, tag`). Repeat with the same descriptor and the same delay:
   the decision moves as the factor `k` converges. CALUPD counts the updates.
6. To retune, write a new row to PARAM and dispatch again. PARAM_LOCK (CTRL
   bit 3) makes the rows read-only until the next reset.

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

None. The RP2040 on the Tiny Tapeout demo board drives the three SPI pins
from MicroPython. A whole dispatch -- 17 bytes of descriptor, GO, and a
RESULT read -- is about 30 bytes: under a millisecond with the RP2040's SPI
peripheral at 1 MHz, a few milliseconds bit-banged.

## Verification before tapeout

- 18 cocotb tests from the pins: the roofline crossover, retuning that moves
  the decision, a calibration loop that closes on real elapsed cycles,
  back-pressure, every op class and data type terminating, reset in the middle
  of a frame, tag exhaustion, stale and out-of-range completions, torn frames
- 15 deliberate breaks of the design (`test/mutate_sim.py`), each of which
  must make a named test fail
- In the parent repository, which compiles the same dispatcher modules: the
  shared cost engine makes the same decision as five parallel ones on every
  descriptor given (`make cost-mux`), the SPI slave is proved by induction,
  and the dispatcher runs against real engine models (`make systile`)

## Timing and area

The last signed-off harden is v2 (2026-10-05, 4x4): every corner met setup at
66 ns, slow-corner slack +2.199 ns, DRC, LVS and antenna clean, 17 of 17
tests on the hardened netlist. v3 is the same logic minus the parts listed at
the top of `info.yaml`, on 3x4 tiles; its harden is pending.

| | v2 (4x4) | v3 (3x4) |
|---|---:|---:|
| cells, yosys + abc on sky130 | 15,574 | 11,964 |
| cell area, um^2 | 147,278 | 113,939 |
| tags | 8 | 4 |
| host interfaces | serial pins and SPI | SPI |

The decision takes about thirteen cycles at any clock: five engines on one
shared cost engine, two cycles each. The clock is 15.15 MHz (66 ns).
