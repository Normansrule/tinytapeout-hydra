"""
test.py

HYDRA-130 TT-A - cocotb test for the Mathematical Operation MUX tile
Copyright (c) 2026 Aleksander J. Norman
SPDX-License-Identifier: Apache-2.0

Runs against RTL by default and against the gate-level netlist with GATES=yes,
which is what TinyTapeout's CI does. The same test must pass both.

The descriptor is 128 bits and the tile has 8 input pins, so it is shifted in
serially, MSB first, then a `go` pulse presents it.

WHAT IS ACTUALLY BEING CHECKED
------------------------------
Not "did a dispatch happen". The tile is asked for TWO tile sizes on either
side of the roofline crossover the whole cost model turns on, and the answers
must DIFFER:

    GEMM INT8 4x4x4  ->  SIMD, because the array's 64-cycle setup dominates
    GEMM INT8 8x8x8  ->  TPU,  because compute overtakes setup

A test confirming only that some engine was chosen would pass against a
dispatch unit hardwired to a constant.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# Encodings mirrored from rtl/mom/mom_pkg.sv. These were WRONG in the first
# version -- OPC_GEMM was guessed as 4 when it is 3 -- and the failure looked
# like a broken cost model rather than a broken constant. Copy them from the
# package; do not infer them.
OPC_GEMM = 3
DT_INT8 = 0
DT_POLY_Q = 5
LAT_BALANCED = 1
PWR_BALANCED = 1

WD_W = 128

ENG_CPU, ENG_SIMD, ENG_TPU, ENG_NTT, ENG_CRYPTO = range(5)
ENG_NAME = {0: "CPU", 1: "SIMD", 2: "TPU", 3: "NTT", 4: "CRYPTO"}


def build_descriptor(op_class, dtype, lat, pwr, m, n, k, nbytes,
                     src_loc=0, tag=0):
    """Pack a work_desc_t exactly as the RTL unpacks it.

    In a SystemVerilog packed struct the FIRST field is the MOST significant,
    so the fields are appended from the top down. The first version of this
    function packed LSB-first and every dispatch came back plausible and wrong
    -- a matrix multiply became a scalar op with absurd dimensions, and the
    tile happily chose an engine for it.

    That is why the test checks a CROSSOVER rather than a single expected
    engine: a wrong descriptor still produces an answer, and only requiring two
    DIFFERENT answers exposes it.

    Total width must be exactly 128 bits, which is asserted below.
    """
    fields = [
        (op_class, 4), (dtype, 3), (lat, 2), (pwr, 2),
        (m, 16), (n, 16), (k, 16), (nbytes, 24),
        (src_loc, 2), (tag, 8), (0, 35),          # src_loc, tag, reserved
    ]
    assert sum(w for _, w in fields) == WD_W, "descriptor width mismatch"

    d = 0
    for val, width in fields:
        d = (d << width) | (val & ((1 << width) - 1))
    return d


async def reset(dut):
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.ena.value = 1
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


async def shift_and_go(dut, desc):
    """Shift 128 bits MSB first, then pulse go.

    `go` is deliberately held high for several cycles. The tile edge-detects
    it, and holding it is exactly what software driving GPIO will do -- a
    level-sensitive design would re-dispatch every cycle until every tag was
    consumed.
    """
    for i in range(WD_W - 1, -1, -1):
        bit = (desc >> i) & 1
        dut.ui_in.value = bit | (1 << 1)          # sdi + shift
        await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 1)

    dut.ui_in.value = 1 << 2                       # go, held
    await ClockCycles(dut.clk, 6)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 4)


def decode_status(dut):
    uo = int(dut.uo_out.value)
    uio = int(dut.uio_out.value)
    return {
        "engine": uo & 0x7,
        "dispatched": (uo >> 3) & 1,
        "unsupported": (uo >> 4) & 1,
        "stale": (uo >> 5) & 1,
        "busy": (uo >> 6) & 1,
        "ready": (uo >> 7) & 1,
        "tag": uio & 0xF,
        "margin": (uio >> 4) & 0xF,
    }


@cocotb.test()
async def test_roofline_crossover(dut):
    """The two tile sizes must choose DIFFERENT engines."""
    dut._log.info("start")
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())   # ~18 MHz, matches signoff (s139)
    await reset(dut)

    assert int(dut.uio_oe.value) == 0xFF, "every bidirectional must be an output"

    small = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED,
                             4, 4, 4, 48)
    await shift_and_go(dut, small)
    s = decode_status(dut)
    dut._log.info(f"4x4x4 -> engine {s['engine']} ({ENG_NAME.get(s['engine'])}) "
                  f"tag {s['tag']} margin {s['margin']}")
    assert s["dispatched"], "small tile was not dispatched"
    assert not s["unsupported"], "GEMM INT8 reported unsupported"

    # Retire it so the scoreboard does not accumulate outstanding work.
    dut.ui_in.value = (s["tag"] << 4) | (1 << 3)
    await ClockCycles(dut.clk, 4)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 4)

    large = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED,
                             8, 8, 8, 192)
    await shift_and_go(dut, large)
    l = decode_status(dut)
    dut._log.info(f"8x8x8 -> engine {l['engine']} ({ENG_NAME.get(l['engine'])}) "
                  f"tag {l['tag']} margin {l['margin']}")
    assert l["dispatched"], "large tile was not dispatched"
    assert not l["unsupported"], "GEMM INT8 reported unsupported"

    # The point of the whole test.
    assert s["engine"] != l["engine"], (
        f"both tiles chose engine {s['engine']}; the cost model is not "
        "discriminating and this test would pass against a dispatch unit "
        "hardwired to a constant"
    )
    dut._log.info(f"crossover confirmed: {ENG_NAME.get(s['engine'])} "
                  f"then {ENG_NAME.get(l['engine'])}")


@cocotb.test()
async def test_unsupported_is_retired(dut):
    """A descriptor no engine can execute must be REPORTED, not retried forever.

    An early version of the MOM looped on such a descriptor until reset, which
    is a hang rather than an error. GEMM over a polynomial-ring data type is
    the natural example: no engine performs a matrix multiply over ring
    elements.
    """
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    await reset(dut)

    bad = build_descriptor(OPC_GEMM, DT_POLY_Q, LAT_BALANCED, PWR_BALANCED,
                           64, 64, 64, 4096)
    await shift_and_go(dut, bad)
    s = decode_status(dut)
    dut._log.info(f"unsupported descriptor: unsupported={s['unsupported']} "
                  f"dispatched={s['dispatched']}")
    assert s["unsupported"], "an impossible descriptor was not flagged"
    assert not s["dispatched"], "an impossible descriptor was dispatched anyway"


@cocotb.test()
async def test_edge_detected_go(dut):
    """A held `go` must allocate exactly one tag per assertion, not per cycle.

    Requests are left OUTSTANDING here on purpose. The scoreboard hands out the
    lowest FREE tag, so completing between requests always returns tag 0 and
    proves nothing either way. Leaving them in flight forces the tag to
    advance, and the RATE it advances at is what distinguishes edge from level
    detection.
    """
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    await reset(dut)

    desc = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED,
                            8, 8, 8, 192)
    tags = []
    for _ in range(3):
        await shift_and_go(dut, desc)
        tags.append(decode_status(dut)["tag"])

    dut._log.info(f"tags allocated with `go` held 6 cycles: {tags}")
    assert tags == [0, 1, 2], (
        f"expected consecutive tags 0,1,2 but got {tags}; a level-sensitive "
        "`go` would consume several tags per request"
    )


# =============================================================================
# Session 136 -- silicon-readiness tests.
#
# The three tests above prove the tile does its job. These prove it cannot be
# put into a state it does not recover from, which is what matters once the
# design is on a wafer and cannot be patched. Each one targets a way first
# silicon commonly fails: an unreset flop driving a pin, a reset that lands
# mid-transaction, a resource that runs out and is never given back, a
# descriptor the machine can neither execute nor reject, and a bogus
# completion from a confused host.
# =============================================================================

async def retire(dut, tag):
    dut.ui_in.value = (tag << 4) | (1 << 3)
    await ClockCycles(dut.clk, 4)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, 4)


@cocotb.test()
async def test_no_x_on_any_pin_after_reset(dut):
    """Every output pin must be a clean 0 or 1 from the first clock after
    reset -- no X, no Z -- and must stay that way with no stimulus at all.

    An unreset register that feeds a pin is invisible in RTL simulation until
    something reads the pin, and invisible on silicon until the board misreads
    it. This is the cheapest test in the file and the one most worth having.
    """
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.ena.value = 1
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    for cyc in range(200):
        await ClockCycles(dut.clk, 1)
        for name in ("uo_out", "uio_out", "uio_oe"):
            v = getattr(dut, name).value
            assert v.is_resolvable, f"{name} has X/Z {cyc} cycles after reset: {v}"
    s = decode_status(dut)
    assert s["ready"], "tile not ready after reset with nothing outstanding"
    assert not s["busy"] and not s["dispatched"] and not s["unsupported"] and not s["stale"], \
        f"status not clean after reset: {s}"


@cocotb.test()
async def test_reset_mid_transaction(dut):
    """Reset asserted halfway through a descriptor shift must leave the tile
    in a state where the NEXT full descriptor dispatches normally.

    On a board, reset comes from a button or a supervisor and lands whenever
    it lands. A shift register that keeps its half-loaded contents through
    reset would corrupt the first real descriptor after every power glitch.
    """
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    await reset(dut)

    junk = build_descriptor(OPC_GEMM, DT_POLY_Q, 3, 3, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFFFF)
    for i in range(WD_W - 1, WD_W // 2, -1):            # half the bits only
        dut.ui_in.value = ((junk >> i) & 1) | (1 << 1)
        await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0

    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 3)

    good = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED, 4, 4, 4, 48)
    await shift_and_go(dut, good)
    s = decode_status(dut)
    assert s["dispatched"] and not s["unsupported"], \
        f"first descriptor after a mid-shift reset did not dispatch: {s}"
    assert s["tag"] == 0, f"tags were not cleared by reset (got tag {s['tag']})"
    await retire(dut, s["tag"])


@cocotb.test()
async def test_tag_exhaustion_and_recovery(dut):
    """Allocate every tag without retiring any, then present one more.

    The contract this pins down (first written as the opposite, and corrected
    by the tile): `ready` is the PIPELINE's handshake, not "a tag is free".
    With every tag in flight and the pipeline empty, the tile still accepts
    one descriptor and HOLDS it -- nothing is dropped -- and only then drops
    `ready`, which is the back-pressure a host must poll before shifting the
    next one. When a tag is retired, the held descriptor dispatches on its
    own, taking that tag, and `ready` returns. Tags are never duplicated and
    never wrap.
    """
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    await reset(dut)
    NTAG = 8
    desc = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED, 4, 4, 4, 48)

    seen = []
    for i in range(NTAG):
        assert decode_status(dut)["ready"], f"not ready before allocation {i}"
        await shift_and_go(dut, desc)
        s = decode_status(dut)
        assert s["dispatched"], f"allocation {i} did not dispatch: {s}"
        assert s["tag"] not in seen, f"tag {s['tag']} handed out twice"
        seen.append(s["tag"])
    assert sorted(seen) == list(range(NTAG)), f"tags allocated were {seen}"
    s = decode_status(dut)
    assert s["busy"], "busy low with every tag in flight"
    assert s["ready"], "pipeline empty, so the tile should still accept one descriptor"

    # The ninth: accepted into the pipeline, not dispatched, and now the tile
    # says so on the pin.
    await shift_and_go(dut, desc)
    s = decode_status(dut)
    assert not s["dispatched"], "dispatched with no free tag"
    assert not s["unsupported"], "a stalled descriptor was reported as unsupported"
    assert not s["ready"], "ready still high with a descriptor held and no tag free"

    # Retire one tag: the held descriptor must dispatch BY ITSELF with it.
    await retire(dut, seen[3])
    s = decode_status(dut)
    assert s["dispatched"] and s["tag"] == seen[3], \
        f"held descriptor did not dispatch with the freed tag {seen[3]}: {s}"
    assert s["ready"], "ready did not return after the held descriptor dispatched"

    for t in range(NTAG):
        await retire(dut, t)
    s = decode_status(dut)
    assert not s["busy"] and s["ready"], f"not idle after retiring everything: {s}"


@cocotb.test()
async def test_every_descriptor_class_terminates(dut):
    """Sweep every op_class x dtype x latency x power combination with a
    representative shape. For each, the tile must settle to EXACTLY ONE of
    dispatched / unsupported within a bounded number of cycles, and `ready`
    must come back. Both flags, neither flag, or no `ready` is a hang or a
    contradiction that a host cannot recover from without a reset.
    """
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    await reset(dut)
    n_disp = n_unsup = 0
    for opc in range(16):
        for dt in range(8):
            for lat in (0, 3):
                for pwr in (0, 3):
                    desc = build_descriptor(opc, dt, lat, pwr, 8, 8, 8, 192)
                    await shift_and_go(dut, desc)
                    s = decode_status(dut)
                    assert s["dispatched"] != s["unsupported"], \
                        f"opc={opc} dt={dt} lat={lat} pwr={pwr}: both or neither flag set: {s}"
                    if s["dispatched"]:
                        n_disp += 1
                        await retire(dut, s["tag"])
                    else:
                        n_unsup += 1
                    assert decode_status(dut)["ready"], \
                        f"opc={opc} dt={dt}: ready did not return"
    dut._log.info(f"descriptor sweep: {n_disp} dispatched, {n_unsup} unsupported")
    assert n_disp > 0 and n_unsup > 0, "sweep must exercise both outcomes"


@cocotb.test()
async def test_stale_completion_is_flagged_not_absorbed(dut):
    """A completion for a tag that is not in flight must raise `stale` and
    must not free, corrupt, or dispatch anything. A host that loses track of
    its tags is a certainty over a product's life; the tile must survive it.
    """
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    await reset(dut)
    desc = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED, 4, 4, 4, 48)
    await shift_and_go(dut, desc)
    s = decode_status(dut)
    assert s["dispatched"]
    live = s["tag"]

    await retire(dut, (live + 5) % 8)                # not in flight
    s = decode_status(dut)
    assert s["stale"], "completion of a free tag was not flagged"
    assert s["busy"], "a stale completion freed the live tag"

    await retire(dut, live)
    s = decode_status(dut)
    assert not s["busy"], "the real completion did not free the live tag"
    await shift_and_go(dut, desc)
    s = decode_status(dut)
    assert s["dispatched"], "tile did not accept work after a stale completion"
