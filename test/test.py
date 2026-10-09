"""
test.py

HYDRA-130 TT-A v3 (the research tile) - cocotb tests: helpers, and the
silicon-readiness suite
Copyright (c) 2026 Aleksander J. Norman
SPDX-License-Identifier: Apache-2.0

Runs against RTL by default and against the gate-level netlist with GATES=yes,
which is what TinyTapeout's CI does. The same tests must pass both.

v3 talks to the tile only through its SPI register map (hydra_tt_regs.sv).
v1 and v2 also had a pin protocol that shifted the 128-bit descriptor in one
bit per clock; v3 dropped it to save area and power, and the HYDRA-130 chip
keeps it (hydra-skywater130, mom/hydra_mom_pins.sv). The tests here are the
v1/v2 silicon-readiness tests, ported to the register map: same questions,
same contracts.

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

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

# Encodings mirrored from mom_pkg.sv. These were WRONG in the first version --
# OPC_GEMM was guessed as 4 when it is 3 -- and the failure looked like a broken
# cost model rather than a broken constant. Copy them from the package; do not
# infer them.
OPC_GEMM = 3
DT_INT8 = 0
DT_POLY_Q = 5
LAT_BALANCED = 1
PWR_BALANCED = 1

WD_W = 128
NTAG = 4            # v3: four tags (v2 had eight)
CLK_NS = 66         # the signoff clock period

ENG_CPU, ENG_SIMD, ENG_TPU, ENG_NTT, ENG_CRYPTO = range(5)
ENG_NAME = {0: "CPU", 1: "SIMD", 2: "TPU", 3: "NTT", 4: "CRYPTO"}

# ---------------------------------------------------------------------------
# Register map (hydra_tt_regs.sv)
# ---------------------------------------------------------------------------
A_ID, A_WD, A_CTRL, A_ACTION, A_COMP, A_STATUS = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
A_RESULT, A_RESERVED07, A_CALUPD, A_BUSY, A_FENCE, A_PARAM = 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B
A_GLOBAL, A_INFO = 0x0C, 0x0D
LEN = {A_ID: 4, A_WD: 16, A_CTRL: 1, A_ACTION: 1, A_COMP: 1, A_STATUS: 2,
       A_RESULT: 6, A_CALUPD: 2, A_BUSY: 2, A_FENCE: 1, A_PARAM: 6,
       A_GLOBAL: 2, A_INFO: 1}
ID_V3 = 0x48594D33  # "HYM3"

# STATUS bits (16-bit register, MSB first as documented in hydra_tt_regs.sv)
ST_READY, ST_BUSY, ST_PENDING, ST_WD_OK = 15, 14, 13, 12
ST_DISP, ST_UNSUPP, ST_STALE, ST_FRAME = 11, 10, 9, 8
ST_GOERR, ST_FENCE, ST_PLOCK, ST_HOLD = 7, 6, 5, 4

HALF = 5            # clk cycles per SCK half period: SCK = clk/10, inside clk/8


def build_descriptor(op_class, dtype, lat, pwr, m, n, k, nbytes,
                     src_loc=0, tag=0):
    """Pack a work_desc_t exactly as the RTL unpacks it.

    In a SystemVerilog packed struct the FIRST field is the MOST significant,
    so the fields are appended from the top down. The first version of this
    function packed LSB-first and every dispatch came back plausible and wrong
    -- a matrix multiply became a scalar op with absurd dimensions, and the
    tile happily chose an engine for it. That is why the tests check a
    CROSSOVER rather than a single expected engine.
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


SMALL = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED, 4, 4, 4, 48)
LARGE = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED, 8, 8, 8, 192)


def bit(v, n):
    return (v >> n) & 1


class Tile:
    """An SPI mode-0 host, bit-banged on ui_in[2:0]."""

    def __init__(self, dut):
        self.dut = dut
        self.pins = 0b100          # CSn idle high

    def _set(self, sck=None, copi=None, csn=None):
        if sck is not None:
            self.pins = (self.pins & ~0b001) | (sck & 1)
        if copi is not None:
            self.pins = (self.pins & ~0b010) | ((copi & 1) << 1)
        if csn is not None:
            self.pins = (self.pins & ~0b100) | ((csn & 1) << 2)
        self.dut.ui_in.value = self.pins

    async def xfer(self, tx_bytes, stop_after=None):
        """One CS-framed transfer. Returns the bytes seen on CIPO.

        stop_after=N returns after N bytes with CSn still LOW, for tests that
        interrupt a frame (a reset mid-transaction)."""
        clk = self.dut.clk
        self._set(sck=0, csn=0)
        await ClockCycles(clk, 2 * HALF)
        rx = []
        for j, b in enumerate(tx_bytes):
            if stop_after is not None and j == stop_after:
                return rx
            v = 0
            for i in range(7, -1, -1):
                self._set(copi=(b >> i) & 1)
                await ClockCycles(clk, HALF)
                # CIPO is sampled by the host on the rising edge.
                v = (v << 1) | (int(self.dut.uo_out.value) & 1)
                self._set(sck=1)
                await ClockCycles(clk, HALF)
                self._set(sck=0)
            rx.append(v)
        await ClockCycles(clk, HALF)
        self._set(csn=1)
        await ClockCycles(clk, 2 * HALF)
        return rx

    async def write(self, addr, value, nbytes=None):
        n = LEN[addr] if nbytes is None else nbytes
        data = [(value >> (8 * (n - 1 - i))) & 0xFF for i in range(n)]
        await self.xfer([addr & 0x7F] + data)

    async def read(self, addr, nbytes=None):
        n = LEN.get(addr, 1) if nbytes is None else nbytes
        rx = await self.xfer([0x80 | addr] + [0] * n)
        v = 0
        for b in rx[1:]:
            v = (v << 8) | b
        return v, rx[0]

    async def status(self):
        v, _ = await self.read(A_STATUS)
        return v

    async def go(self):
        await self.write(A_ACTION, 0x01)
        await ClockCycles(self.dut.clk, 10)

    async def clear(self):
        await self.write(A_ACTION, 0x02)

    async def comp(self, tag):
        await self.write(A_COMP, tag & 0xF)
        await ClockCycles(self.dut.clk, 4)

    async def result(self):
        v, _ = await self.read(A_RESULT)
        return {"engine": (v >> 45) & 7, "tag": (v >> 41) & 0xF,
                "margin": (v >> 8) & 0xFFFFFFFF, "err_tag": v & 0xFF}

    async def dispatch(self, desc):
        await self.write(A_WD, desc)
        await self.go()
        st = await self.status()
        return st, await self.result()

    def pins_status(self):
        """The summary pins, which need no SPI traffic to read."""
        uo = int(self.dut.uo_out.value)
        uio = int(self.dut.uio_out.value)
        return {"irq": (uo >> 1) & 1, "engine": (uo >> 2) & 7,
                "dispatched": (uo >> 5) & 1, "busy": (uo >> 6) & 1,
                "ready": (uo >> 7) & 1, "tag": uio & 0xF, "margin": (uio >> 4) & 0xF}


async def start(dut, ui_in_during_reset=0x04):
    """Clock, reset, and an SPI host. The default holds CSn high through reset;
    a v2 host held the strap 0xA4, and a bare demoboard holds 0x00."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = ui_in_during_reset
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    t = Tile(dut)
    t._set(sck=0, copi=0, csn=1)
    await ClockCycles(dut.clk, 2)
    return t


# =============================================================================
# The job: a decision that depends on the work
# =============================================================================

@cocotb.test()
async def test_roofline_crossover(dut):
    """The two tile sizes must choose DIFFERENT engines: SIMD, then TPU."""
    t = await start(dut)
    assert int(dut.uio_oe.value) == 0xFF, "every bidirectional must be an output"

    st, s = await t.dispatch(SMALL)
    dut._log.info(f"4x4x4 -> {ENG_NAME.get(s['engine'])} tag {s['tag']} margin {s['margin']}")
    assert bit(st, ST_DISP) and not bit(st, ST_UNSUPP), f"small not dispatched: {st:#06x}"
    await t.comp(s["tag"])

    await t.clear()
    st, l = await t.dispatch(LARGE)
    dut._log.info(f"8x8x8 -> {ENG_NAME.get(l['engine'])} tag {l['tag']} margin {l['margin']}")
    assert bit(st, ST_DISP) and not bit(st, ST_UNSUPP), f"large not dispatched: {st:#06x}"

    assert s["engine"] != l["engine"], (
        f"both tiles chose engine {s['engine']}; the cost model is not "
        "discriminating and this test would pass against a dispatch unit "
        "hardwired to a constant")
    assert (s["engine"], l["engine"]) == (ENG_SIMD, ENG_TPU), \
        f"crossover went {ENG_NAME[s['engine']]} -> {ENG_NAME[l['engine']]}, expected SIMD -> TPU"
    await t.comp(l["tag"])


@cocotb.test()
async def test_unsupported_is_retired(dut):
    """A descriptor no engine can execute must be REPORTED, not retried forever.

    An early version of the MOM looped on such a descriptor until reset, which
    is a hang rather than an error. GEMM over a polynomial-ring data type is
    the natural example: no engine performs a matrix multiply over ring
    elements.
    """
    t = await start(dut)
    bad = build_descriptor(OPC_GEMM, DT_POLY_Q, LAT_BALANCED, PWR_BALANCED, 64, 64, 64, 4096)
    st, _ = await t.dispatch(bad)
    assert bit(st, ST_UNSUPP), f"an impossible descriptor was not flagged: {st:#06x}"
    assert not bit(st, ST_DISP), "an impossible descriptor was dispatched anyway"
    assert bit(st, ST_READY) and not bit(st, ST_PENDING), "the tile did not let go of it"
    assert t.pins_status()["irq"], "IRQ not raised for an unsupported descriptor"


@cocotb.test()
async def test_one_go_one_dispatch(dut):
    """Each GO must allocate exactly one tag, however long the tile waits.

    v1/v2 checked the same contract as an edge detector on a held `go` pin.
    On the register map the risk is the handshake: if the request were not
    retired when the MOM takes it, one GO would dispatch again every cycle
    until the tags ran out. Tags are left OUTSTANDING so a repeat would show:
    the scoreboard hands out the lowest free tag.
    """
    t = await start(dut)
    tags = []
    for _ in range(3):
        st, r = await t.dispatch(LARGE)
        assert bit(st, ST_DISP)
        tags.append(r["tag"])
        await ClockCycles(dut.clk, 60)            # several decisions' worth
    busy, _ = await t.read(A_BUSY)
    dut._log.info(f"tags {tags}, busy {busy:#06b}")
    assert tags == [0, 1, 2], f"expected tags 0,1,2, got {tags}"
    assert busy == 0b0111, f"three GOs should hold three tags, busy = {busy:#06b}"


# =============================================================================
# Session 136 -- silicon-readiness tests, ported to the register map in v3.
#
# The tests above prove the tile does its job. These prove it cannot be put
# into a state it does not recover from, which is what matters once the design
# is on a wafer and cannot be patched: an unreset flop driving a pin, a reset
# that lands mid-transaction, a resource that runs out and is never given
# back, a descriptor the machine can neither execute nor reject, and a bogus
# completion from a confused host.
# =============================================================================

@cocotb.test()
async def test_no_x_on_any_pin_after_reset(dut):
    """Every output pin must be a clean 0 or 1 from the first clock after
    reset -- no X, no Z -- and must stay that way with no stimulus at all.

    The host here holds every input at 0 through reset, as a bare demoboard
    does. That leaves CSn LOW, so the SPI block sees a frame open with no
    clocks in it. It must not count as an error, and the first real frame
    afterwards must work.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
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
    t = Tile(dut)
    p = t.pins_status()
    assert p["ready"], "tile not ready after reset with nothing outstanding"
    assert not (p["busy"] or p["dispatched"] or p["irq"]), f"pins not clean after reset: {p}"

    t._set(sck=0, copi=0, csn=1)                  # the empty frame ends here
    await ClockCycles(dut.clk, 4)
    assert (await t.read(A_ID))[0] == ID_V3
    st = await t.status()
    assert (st & 0x0F80) == 0, f"the empty frame left a flag: {st:#06x}"


@cocotb.test()
async def test_reset_mid_transaction(dut):
    """Reset asserted halfway through a descriptor write must leave the tile
    in a state where the NEXT full descriptor dispatches normally.

    On a board, reset comes from a button or a supervisor and lands whenever
    it lands. A descriptor register that kept its half-written contents, or a
    WD_OK that survived, would corrupt the first real descriptor after every
    power glitch.
    """
    t = await start(dut)
    junk = build_descriptor(OPC_GEMM, DT_POLY_Q, 3, 3, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFFFF)
    data = [(junk >> (8 * (15 - i))) & 0xFF for i in range(16)]
    await t.xfer([A_WD] + data, stop_after=9)     # command + 8 of 16 bytes, CSn still low

    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    t._set(sck=0, copi=0, csn=1)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    st = await t.status()
    assert not bit(st, ST_WD_OK), "WD_OK survived a reset"
    await t.go()
    st = await t.status()
    assert bit(st, ST_GOERR) and not bit(st, ST_DISP), "GO after reset presented a stale descriptor"
    await t.clear()

    st, r = await t.dispatch(SMALL)
    assert bit(st, ST_DISP) and not bit(st, ST_UNSUPP), \
        f"first descriptor after a mid-frame reset did not dispatch: {st:#06x}"
    assert r["tag"] == 0, f"tags were not cleared by reset (got tag {r['tag']})"
    assert r["engine"] == ENG_SIMD, "the small multiply went to the wrong engine after reset"


@cocotb.test()
async def test_tag_exhaustion_and_recovery(dut):
    """Allocate every tag without retiring any, then keep offering work.

    The contract: `ready` is the PIPELINE's handshake, not "a tag is free".
    With every tag in flight and the pipeline empty, the tile still accepts
    descriptors and HOLDS them -- nothing is dropped -- and only then drops
    `ready`, which is the back-pressure a host must poll. When a tag is
    retired, a held descriptor dispatches on its own, taking that tag. Tags are
    never duplicated and never wrap.
    """
    t = await start(dut)
    seen = []
    for i in range(NTAG):
        assert bit(await t.status(), ST_READY), f"not ready before allocation {i}"
        st, r = await t.dispatch(SMALL)
        assert bit(st, ST_DISP), f"allocation {i} did not dispatch: {st:#06x}"
        assert r["tag"] not in seen, f"tag {r['tag']} handed out twice"
        seen.append(r["tag"])
        await t.clear()
    assert sorted(seen) == list(range(NTAG)), f"tags allocated were {seen}"
    busy, _ = await t.read(A_BUSY)
    assert busy == (1 << NTAG) - 1, f"busy bitmap {busy:#x} with every tag in flight"
    st = await t.status()
    assert bit(st, ST_BUSY) and bit(st, ST_READY), f"{st:#06x}"

    # Keep offering until the tile stops accepting. The pipeline holds a few
    # (features, cost-engine mid-register, cost register, the request itself);
    # the CONTRACT is depth-agnostic: nothing is dropped, `ready` falls when
    # the pipeline is full, and none dispatches without a tag.
    held = 0
    for _ in range(8):
        st = await t.status()
        if not bit(st, ST_READY) or bit(st, ST_PENDING):
            break
        await t.write(A_WD, SMALL)
        await t.go()
        held += 1
        st = await t.status()
        assert not bit(st, ST_DISP), "dispatched with no free tag"
        assert not bit(st, ST_UNSUPP), "a stalled descriptor was reported as unsupported"
        assert not bit(st, ST_GOERR), "GO refused while the tile reported ready"
    assert 1 <= held <= 5, f"pipeline held {held} descriptors; expected 1..5"
    assert not bit(await t.status(), ST_READY), "ready still high with the pipeline full and no tag free"

    # Retire one tag: a held descriptor must dispatch BY ITSELF with it.
    await t.comp(seen[2])
    await ClockCycles(dut.clk, 40)
    st = await t.status()
    r = await t.result()
    assert bit(st, ST_DISP) and r["tag"] == seen[2], \
        f"held descriptor did not dispatch with the freed tag {seen[2]}: {st:#06x} {r}"

    # Drain: retire whatever is busy until nothing is, then the tile is idle.
    for _ in range(12):
        busy, _ = await t.read(A_BUSY)
        if busy == 0 and bit(await t.status(), ST_READY) and not bit(await t.status(), ST_PENDING):
            break
        for tag in range(NTAG):
            if (busy >> tag) & 1:
                await t.comp(tag)
        await ClockCycles(dut.clk, 40)
    busy, _ = await t.read(A_BUSY)
    st = await t.status()
    assert busy == 0 and bit(st, ST_READY) and not bit(st, ST_BUSY), \
        f"not idle after retiring everything: busy {busy:#x} status {st:#06x}"


@cocotb.test()
async def test_every_descriptor_class_terminates(dut):
    """Sweep every op_class x dtype x latency x power combination with a
    representative shape. For each, the tile must settle to EXACTLY ONE of
    dispatched / unsupported, and `ready` must come back. Both flags, neither
    flag, or no `ready` is a hang or a contradiction that a host cannot
    recover from without a reset.
    """
    t = await start(dut)
    # The gate-level netlist simulates many times slower than RTL, so there the
    # sweep keeps every op class and dtype at the two extremes of latency and power.
    gl = os.environ.get("GATES") == "yes"
    lp = [(0, 0), (3, 3)] if gl else [(lat, pwr) for lat in (0, 3) for pwr in (0, 3)]
    n_disp = n_unsup = 0
    for opc in range(16):
        for dt in range(8):
            for lat, pwr in lp:
                await t.clear()
                st, r = await t.dispatch(build_descriptor(opc, dt, lat, pwr, 8, 8, 8, 192))
                where = f"opc={opc} dt={dt} lat={lat} pwr={pwr}"
                assert bit(st, ST_DISP) != bit(st, ST_UNSUPP), \
                    f"{where}: both or neither flag set: {st:#06x}"
                if bit(st, ST_DISP):
                    n_disp += 1
                    await t.comp(r["tag"])
                else:
                    n_unsup += 1
                assert bit(await t.status(), ST_READY), f"{where}: ready did not return"
    dut._log.info(f"descriptor sweep: {n_disp} dispatched, {n_unsup} unsupported")
    assert n_disp > 0 and n_unsup > 0, "sweep must exercise both outcomes"


@cocotb.test()
async def test_stale_completion_is_flagged_not_absorbed(dut):
    """A completion for a tag that is not in flight -- or does not exist --
    must raise `stale` and must not free, corrupt, or dispatch anything. A
    host that loses track of its tags is a certainty over a product's life;
    the tile must survive it.
    """
    t = await start(dut)
    st, r = await t.dispatch(SMALL)
    assert bit(st, ST_DISP)
    live = r["tag"]

    for bogus in ((live + 1) % NTAG, NTAG, 15):   # free, first nonexistent, last nonexistent
        await t.clear()
        await t.comp(bogus)
        st = await t.status()
        assert bit(st, ST_STALE), f"completion of tag {bogus} was not flagged"
        busy, _ = await t.read(A_BUSY)
        assert busy == 1 << live, f"completion of tag {bogus} changed the busy set to {busy:#x}"

    await t.comp(live)
    assert (await t.read(A_BUSY))[0] == 0, "the real completion did not free the live tag"
    await t.clear()
    st, r = await t.dispatch(SMALL)
    assert bit(st, ST_DISP), "tile did not accept work after a stale completion"
