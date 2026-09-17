"""
test_regs.py

HYDRA-130 TT-A v2 -- cocotb tests for the REGISTER personality
Copyright (c) 2026 Aleksander J. Norman
SPDX-License-Identifier: Apache-2.0

Runs in the same simulation as test.py (see COCOTB_TEST_MODULES in the
Makefile). Every test here resets with the strap ui_in[7:4] = 0xA; every test
in test.py resets with ui_in = 0. Both files passing in one run is the
evidence that the two personalities coexist.

The SPI driver bit-bangs mode 0 at 5 clk per half period (about 1.8 MHz at
the 55 ns signoff clock), inside the clk/8 limit hydra_tt_spi.sv documents.

As in test.py, the headline checks require DIFFERENT outcomes (a crossover, a
retune that moves the decision, a closed calibration loop), because a check
that only confirms "something happened" passes against a constant.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from test import (build_descriptor, OPC_GEMM, DT_INT8, DT_POLY_Q,
                  LAT_BALANCED, PWR_BALANCED, ENG_NAME, ENG_SIMD, ENG_TPU)

A_ID, A_WD, A_CTRL, A_ACTION, A_COMP, A_STATUS = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
A_RESULT, A_LASTWD, A_CALUPD, A_BUSY, A_FENCE, A_PARAM = 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B
A_GLOBAL, A_INFO = 0x0C, 0x0D
LEN = {A_ID: 4, A_WD: 16, A_CTRL: 1, A_ACTION: 1, A_COMP: 1, A_STATUS: 2,
       A_RESULT: 6, A_LASTWD: 16, A_CALUPD: 2, A_BUSY: 2, A_FENCE: 1,
       A_PARAM: 6, A_GLOBAL: 2, A_INFO: 1}

# STATUS bits (16-bit register, MSB first as documented in hydra_tt_regs.sv)
ST_READY, ST_BUSY, ST_PENDING, ST_WD_OK = 15, 14, 13, 12
ST_DISP, ST_UNSUPP, ST_STALE, ST_FRAME = 11, 10, 9, 8
ST_GOERR, ST_FENCE, ST_PLOCK, ST_HOLD = 7, 6, 5, 4

HALF = 5            # clk cycles per SCK half period

# Parameter rows, copied from mom_param_rom.sv (do not infer them).
#   {p_peak_log2[4], t_setup[12], bw_bytes_log2[4], eps_op[8], dtype_msk[6], opc_msk[9]}
def row(p_peak, t_setup, bw, eps, dtype_msk, opc_msk):
    return ((p_peak << 39) | (t_setup << 27) | (bw << 23) | (eps << 15)
            | (dtype_msk << 9) | opc_msk)

DEF_TPU = row(7, 64, 5, 2, 0b000011, 0b000011000)


class Tile:
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

    async def xfer(self, tx_bytes):
        """One CS-framed transfer. Returns the bytes seen on CIPO."""
        clk = self.dut.clk
        self._set(sck=0, csn=0)
        await ClockCycles(clk, 2 * HALF)
        rx = []
        for b in tx_bytes:
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


def bit(v, n):
    return (v >> n) & 1


async def reset_reg_mode(dut):
    cocotb.start_soon(Clock(dut.clk, 55, unit="ns").start())
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0xA4          # strap A, CSn high
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    t = Tile(dut)
    t._set(sck=0, copi=0, csn=1)    # release the strap nibble
    await ClockCycles(dut.clk, 2)
    return t


SMALL = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED, 4, 4, 4, 48)
LARGE = build_descriptor(OPC_GEMM, DT_INT8, LAT_BALANCED, PWR_BALANCED, 8, 8, 8, 192)


@cocotb.test()
async def test_reg_strap_id_and_defaults(dut):
    """The strap selects the register personality, and the reset values match
    v1's tie-offs exactly (GLOBAL = {4, 12, 8})."""
    t = await reset_reg_mode(dut)
    for name in ("uo_out", "uio_out", "uio_oe"):
        assert getattr(dut, name).value.is_resolvable, f"{name} has X/Z"
    assert int(dut.uio_oe.value) == 0xFF

    ident, first = await t.read(A_ID)
    assert ident == 0x48594D32, f"ID read {ident:#x}"
    assert bit(first, 7), f"status byte during command shows not ready: {first:#04x}"
    assert (await t.read(A_INFO))[0] == 8, "NTAG"
    assert (await t.read(A_GLOBAL))[0] == 0x4C8, "GLOBAL defaults differ from v1 tie-offs"
    assert (await t.read(A_CTRL))[0] == 0
    st = await t.status()
    assert bit(st, ST_READY) and not bit(st, ST_BUSY) and not bit(st, ST_WD_OK)
    assert (st & 0x0F80) == 0, f"sticky flags set after reset: {st:#06x}"
    assert (int(dut.uo_out.value) >> 1) & 1 == 0, "IRQ high after reset"


@cocotb.test()
async def test_reg_crossover_and_readback(dut):
    """Same roofline crossover as the legacy test, through the register map,
    plus the values v1 could not show: the full 32-bit margin and the
    descriptor as dispatched."""
    t = await reset_reg_mode(dut)

    await t.write(A_WD, SMALL)
    assert (await t.read(A_WD))[0] == SMALL, "WD readback"
    assert bit(await t.status(), ST_WD_OK)
    await t.go()
    st = await t.status()
    s = await t.result()
    assert bit(st, ST_DISP) and not bit(st, ST_UNSUPP), f"small: {st:#06x}"
    assert (await t.read(A_LASTWD))[0] == SMALL, "LASTWD != descriptor sent"
    await t.comp(s["tag"])

    st, l = await t.dispatch(LARGE)
    assert bit(st, ST_DISP), f"large: {st:#06x}"
    assert (await t.read(A_LASTWD))[0] == LARGE
    dut._log.info(f"4x4x4 -> {ENG_NAME[s['engine']]} margin {s['margin']}; "
                  f"8x8x8 -> {ENG_NAME[l['engine']]} margin {l['margin']}")
    assert s["engine"] != l["engine"], "no crossover through the register map"
    assert (s["engine"], l["engine"]) == (ENG_SIMD, ENG_TPU), \
        "register mode disagrees with the legacy crossover"
    # Pin summaries agree with the register.
    uo = int(dut.uo_out.value)
    assert (uo >> 2) & 7 == l["engine"] and (uo >> 5) & 1
    assert int(dut.uio_out.value) & 0xF == l["tag"]
    await t.comp(l["tag"])


@cocotb.test()
async def test_reg_param_retune_moves_the_decision(dut):
    """The claim v1 could not test on silicon: the dispatch policy is tunable
    after tapeout. Make the TPU's setup cost enormous; the 8x8x8 multiply must
    leave the TPU. Then PARAM_LOCK must make the same write inert."""
    t = await reset_reg_mode(dut)
    slow_tpu = row(7, 4000, 5, 2, 0b000011, 0b000011000)
    await t.write(A_PARAM, (ENG_TPU << 43) | slow_tpu)
    await ClockCycles(dut.clk, 4)
    st, r = await t.dispatch(LARGE)
    dut._log.info(f"8x8x8 with TPU t_setup=4000 -> {ENG_NAME[r['engine']]}")
    assert bit(st, ST_DISP)
    assert r["engine"] != ENG_TPU, "retuning the TPU row did not move the decision"
    await t.comp(r["tag"])

    # Restoring the default row restores the decision.
    await t.write(A_PARAM, (ENG_TPU << 43) | DEF_TPU)
    st, r = await t.dispatch(LARGE)
    assert r["engine"] == ENG_TPU, "restoring the default row did not restore TPU"
    await t.comp(r["tag"])

    # Lock, then try again: the write must be ignored.
    await t.write(A_CTRL, 0x08)
    assert bit(await t.status(), ST_PLOCK)
    await t.write(A_CTRL, 0x00)                    # lock is sticky
    assert bit(await t.status(), ST_PLOCK), "PARAM_LOCK cleared by a write"
    await t.write(A_PARAM, (ENG_TPU << 43) | slow_tpu)
    st, r = await t.dispatch(LARGE)
    assert r["engine"] == ENG_TPU, "a PARAM write took effect while locked"


@cocotb.test()
async def test_reg_hold_backpressure(dut):
    """With HOLD set the MOM may accept work but must not dispatch it.
    Releasing HOLD dispatches exactly the held descriptor."""
    t = await reset_reg_mode(dut)
    await t.write(A_CTRL, 0x01)
    await t.write(A_WD, LARGE)
    await t.go()
    await ClockCycles(dut.clk, 50)
    st = await t.status()
    assert bit(st, ST_HOLD)
    assert not bit(st, ST_DISP), "dispatched while HOLD was set"
    assert not bit(st, ST_GOERR)
    await t.write(A_CTRL, 0x00)
    await ClockCycles(dut.clk, 10)
    st = await t.status()
    assert bit(st, ST_DISP), "held descriptor did not dispatch on release"
    r = await t.result()
    assert r["engine"] == ENG_TPU
    assert (await t.read(A_LASTWD))[0] == LARGE


@cocotb.test()
async def test_reg_torn_frames_change_nothing(dut):
    """A dropped byte must never become a dispatch or a half-written register."""
    t = await reset_reg_mode(dut)

    # 15 of 16 WD bytes: WD_OK must be clear and GO refused.
    await t.write(A_WD, LARGE >> 8, nbytes=15)
    st = await t.status()
    assert bit(st, ST_FRAME) and not bit(st, ST_WD_OK), f"{st:#06x}"
    await t.go()
    st = await t.status()
    assert bit(st, ST_GOERR) and not bit(st, ST_DISP), "torn descriptor dispatched"
    assert (int(dut.uo_out.value) >> 1) & 1, "IRQ not raised for an error"

    await t.clear()
    st = await t.status()
    assert (st & 0x0F80) == 0, f"CLEAR_STICKY left flags: {st:#06x}"
    assert (int(dut.uo_out.value) >> 1) & 1 == 0

    # Two-byte write to a one-byte register: ignored.
    await t.xfer([A_CTRL, 0x00, 0x01])
    assert (await t.read(A_CTRL))[0] == 0, "long CTRL frame was committed"
    # Write to a read-only register and to an unmapped one: flagged, harmless.
    await t.write(A_ID, 0, nbytes=4)
    assert bit(await t.status(), ST_FRAME)
    await t.clear()
    await t.write(0x55, 0x12, nbytes=1)
    assert bit(await t.status(), ST_FRAME)
    assert (await t.read(0x55, 2))[0] == 0, "unmapped register did not read 0"
    assert (await t.read(A_ID))[0] == 0x48594D32
    # A CS pulse with no bytes at all is not an error.
    await t.clear()
    await t.xfer([])
    assert not bit(await t.status(), ST_FRAME)

    # Double GO: the second is refused while the first is pending? The first
    # is taken within cycles, so a fresh GO afterwards is legal again.
    await t.write(A_WD, LARGE)
    await t.go()
    await t.go()
    st = await t.status()
    assert bit(st, ST_DISP) and not bit(st, ST_GOERR)
    busy, _ = await t.read(A_BUSY)
    assert bin(busy).count("1") == 2, f"expected two tags in flight, busy={busy:#x}"


@cocotb.test()
async def test_reg_completion_calibration_and_fence(dut):
    """Completions free tags and feed the calibration counter; CAL_FREEZE stops
    it; the fence reports exactly the tag it points at."""
    t = await reset_reg_mode(dut)
    st, r = await t.dispatch(LARGE)
    tag = r["tag"]
    busy, _ = await t.read(A_BUSY)
    assert busy == (1 << tag)

    await t.write(A_FENCE, tag)
    assert bit(await t.status(), ST_FENCE), "fence on a busy tag reads free"
    await t.write(A_FENCE, (tag + 1) & 7)
    assert not bit(await t.status(), ST_FENCE), "fence on a free tag reads busy"

    before, _ = await t.read(A_CALUPD)
    await ClockCycles(dut.clk, 200)
    await t.comp(tag)
    after, _ = await t.read(A_CALUPD)
    assert (await t.read(A_BUSY))[0] == 0
    assert after == before + 1, f"calibration counter {before} -> {after}"

    await t.write(A_CTRL, 0x02)                   # freeze
    st, r = await t.dispatch(LARGE)
    await ClockCycles(dut.clk, 200)
    await t.comp(r["tag"])
    frozen, _ = await t.read(A_CALUPD)
    assert frozen == after, "calibration updated while frozen"

    await t.write(A_CTRL, 0x04)                   # calibration reset (level)
    await ClockCycles(dut.clk, 4)
    await t.write(A_CTRL, 0x00)
    assert (await t.read(A_CALUPD))[0] == 0, "CAL_RESET did not clear the counter"

    # Stale completion: flagged, IRQ raised, nothing freed.
    await t.comp(5)
    st = await t.status()
    assert bit(st, ST_STALE) and (int(dut.uo_out.value) >> 1) & 1


@cocotb.test()
async def test_reg_calibration_closes_the_loop(dut):
    """The novel claim, end to end: if the TPU keeps finishing far later than
    predicted, calibration must raise its cost until the 8x8x8 multiply moves
    elsewhere. Latency here is real elapsed clock cycles, as on silicon."""
    t = await reset_reg_mode(dut)
    first = None
    history = []
    for i in range(80):
        st, r = await t.dispatch(LARGE)
        assert bit(st, ST_DISP)
        history.append((ENG_NAME[r["engine"]], r["margin"]))
        if first is None:
            first = r["engine"]
        if r["engine"] != first:
            await t.comp(r["tag"])
            break
        await ClockCycles(dut.clk, 3000)          # TPU far slower than modelled
        await t.comp(r["tag"])
    upd, _ = await t.read(A_CALUPD)
    dut._log.info(f"calibration: {len(history)} dispatches, {upd} updates, "
                  f"trace {history[:3]} ... {history[-3:]}")
    assert first == ENG_TPU
    assert history[-1][0] != "TPU", \
        f"decision never left the TPU after {len(history)} slow completions"


@cocotb.test()
async def test_reg_ignores_legacy_traffic(dut):
    """In the register personality, v1-style pin traffic (shift/go/comp with CS
    held high) must not dispatch, complete, or corrupt anything."""
    t = await reset_reg_mode(dut)
    for i in range(300):
        # sdi/shift toggling on ui[1:0] with CSn=1, comp/go on ui[3:2] kept
        # away from CSn: bit 2 is CSn, so hold it high.
        dut.ui_in.value = 0x04 | (i & 0x03) | (0x08 if i % 7 == 0 else 0)
        await ClockCycles(dut.clk, 1)
    t._set(sck=0, copi=0, csn=1)
    await ClockCycles(dut.clk, 4)
    st = await t.status()
    assert not bit(st, ST_DISP) and not bit(st, ST_BUSY) and not bit(st, ST_STALE), f"{st:#06x}"
    assert not bit(st, ST_FRAME)
    assert (await t.read(A_ID))[0] == 0x48594D32


@cocotb.test()
async def test_reg_margin_pins_are_log_scaled(dut):
    """uio_out[7:4] in the register personality is 1 + floor(log2(margin)).
    Cross-checked against the full 32-bit margin read from RESULT."""
    t = await reset_reg_mode(dut)
    for desc in (SMALL, LARGE):
        st, r = await t.dispatch(desc)
        m = r["margin"]
        exp = 0 if m == 0 else min(15, m.bit_length())
        got = (int(dut.uio_out.value) >> 4) & 0xF
        dut._log.info(f"margin {m} -> nibble {got}")
        assert got == exp, f"margin {m}: nibble {got}, expected {exp}"
        await t.comp(r["tag"])
