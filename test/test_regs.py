"""
test_regs.py

HYDRA-130 TT-A v3 (the research tile) -- cocotb tests for the register map
Copyright (c) 2026 Aleksander J. Norman
SPDX-License-Identifier: Apache-2.0

Runs in the same simulation as test.py (see COCOTB_TEST_MODULES in the
Makefile), which holds the SPI driver. These are the experiments the tile
exists for: retuning the dispatch policy after tapeout, back-pressure, a
calibration loop that closes on real elapsed cycles, and a register map that
survives a host dropping bytes.

As in test.py, the headline checks require DIFFERENT outcomes (a crossover, a
retune that moves the decision, a closed calibration loop), because a check
that only confirms "something happened" passes against a constant.
"""

import cocotb
from cocotb.triggers import ClockCycles

from test import (build_descriptor, bit, start, Tile, OPC_GEMM, DT_INT8,
                  LAT_BALANCED, PWR_BALANCED, ENG_NAME, ENG_SIMD, ENG_TPU, NTAG,
                  ID_V3, A_ID, A_WD, A_CTRL, A_ACTION, A_COMP, A_STATUS, A_RESULT,
                  A_RESERVED07, A_CALUPD, A_BUSY, A_FENCE, A_PARAM, A_GLOBAL, A_INFO,
                  ST_READY, ST_BUSY, ST_PENDING, ST_WD_OK, ST_DISP, ST_UNSUPP,
                  ST_STALE, ST_FRAME, ST_GOERR, ST_FENCE, ST_PLOCK, ST_HOLD,
                  SMALL, LARGE)

# Parameter rows, copied from mom_param_rom.sv (do not infer them).
#   {p_peak_log2[4], t_setup[12], bw_bytes_log2[4], eps_op[8], dtype_msk[6], opc_msk[9]}
def row(p_peak, t_setup, bw, eps, dtype_msk, opc_msk):
    return ((p_peak << 39) | (t_setup << 27) | (bw << 23) | (eps << 15)
            | (dtype_msk << 9) | opc_msk)

DEF_TPU = row(7, 64, 5, 2, 0b000011, 0b000011000)


@cocotb.test()
async def test_reg_id_and_defaults(dut):
    """ID reads "HYM3", INFO reads 4 tags, and the reset values match v1's
    tie-offs exactly (GLOBAL = {4, 12, 8}). Reset here holds ui_in = 0xA4,
    the v2 register-personality strap: v3 ignores the strap, so a v2 host
    still works unchanged."""
    t = await start(dut, ui_in_during_reset=0xA4)
    for name in ("uo_out", "uio_out", "uio_oe"):
        assert getattr(dut, name).value.is_resolvable, f"{name} has X/Z"
    assert int(dut.uio_oe.value) == 0xFF

    ident, first = await t.read(A_ID)
    assert ident == ID_V3, f"ID read {ident:#x}"
    assert bit(first, 7), f"status byte during command shows not ready: {first:#04x}"
    assert (await t.read(A_INFO))[0] == NTAG, "INFO must report the tag count"
    assert (await t.read(A_GLOBAL))[0] == 0x4C8, "GLOBAL defaults differ from v1 tie-offs"
    assert (await t.read(A_CTRL))[0] == 0
    st = await t.status()
    assert bit(st, ST_READY) and not bit(st, ST_BUSY) and not bit(st, ST_WD_OK)
    assert (st & 0x0F80) == 0, f"sticky flags set after reset: {st:#06x}"
    assert (int(dut.uo_out.value) >> 1) & 1 == 0, "IRQ high after reset"


@cocotb.test()
async def test_reg_lastwd_is_reserved(dut):
    """v2's LASTWD (0x07) is gone in v3: it reads 0 and a write is a frame
    error, like any unmapped address, and changes nothing."""
    t = await start(dut)
    st, r = await t.dispatch(LARGE)
    assert bit(st, ST_DISP)
    assert (await t.read(A_RESERVED07, 16))[0] == 0, "0x07 still reads back a descriptor"
    await t.clear()
    await t.write(A_RESERVED07, LARGE, nbytes=16)
    st = await t.status()
    assert bit(st, ST_FRAME) and not bit(st, ST_DISP), f"write to 0x07: {st:#06x}"
    assert (await t.read(A_BUSY))[0] == 1 << r["tag"]


@cocotb.test()
async def test_reg_readback_and_pin_summaries(dut):
    """The descriptor register reads back what was written, RESULT carries the
    full 32-bit margin the pins can only summarise, and the summary pins agree
    with the registers."""
    t = await start(dut)

    await t.write(A_WD, SMALL)
    assert (await t.read(A_WD))[0] == SMALL, "WD readback"
    assert bit(await t.status(), ST_WD_OK)
    await t.go()
    st = await t.status()
    s = await t.result()
    assert bit(st, ST_DISP) and not bit(st, ST_UNSUPP), f"small: {st:#06x}"
    await t.comp(s["tag"])

    st, l = await t.dispatch(LARGE)
    assert bit(st, ST_DISP), f"large: {st:#06x}"
    dut._log.info(f"4x4x4 -> {ENG_NAME[s['engine']]} margin {s['margin']}; "
                  f"8x8x8 -> {ENG_NAME[l['engine']]} margin {l['margin']}")
    assert (s["engine"], l["engine"]) == (ENG_SIMD, ENG_TPU)
    assert l["margin"] > 0, "a decision between engines with different costs has no margin"
    p = t.pins_status()
    assert p["engine"] == l["engine"] and p["dispatched"], f"pins {p} vs RESULT {l}"
    assert p["tag"] == l["tag"], f"tag pins {p['tag']} vs RESULT {l['tag']}"
    await t.comp(l["tag"])


@cocotb.test()
async def test_reg_param_retune_moves_the_decision(dut):
    """The claim v1 could not test on silicon: the dispatch policy is tunable
    after tapeout. Make the TPU's setup cost enormous; the 8x8x8 multiply must
    leave the TPU. Then PARAM_LOCK must make the same write inert."""
    t = await start(dut)
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
    t = await start(dut)
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
    assert r["engine"] == ENG_TPU and r["tag"] == 0, f"the held descriptor came out as {r}"


@cocotb.test()
async def test_reg_torn_frames_change_nothing(dut):
    """A dropped byte must never become a dispatch or a half-written register."""
    t = await start(dut)

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
    assert (await t.read(A_ID))[0] == ID_V3
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
    t = await start(dut)
    st, r = await t.dispatch(LARGE)
    tag = r["tag"]
    busy, _ = await t.read(A_BUSY)
    assert busy == (1 << tag)

    await t.write(A_FENCE, tag)
    assert bit(await t.status(), ST_FENCE), "fence on a busy tag reads free"
    await t.write(A_FENCE, (tag + 1) % NTAG)
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
    t = await start(dut)
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
async def test_reg_pin_noise_with_cs_high_is_ignored(dut):
    """With CSn high, nothing on the other inputs may dispatch, complete, or
    corrupt anything. This is also what a v1/v2 host's pin protocol looks like
    to a v3 tile (shift and sdi toggling, go and comp pulsing), so pointing
    old software at the new tile is harmless."""
    t = await start(dut)
    for i in range(300):
        # bits 0,1 toggle (SCK, COPI); bit 2 (CSn) stays high; bits 3..7 noise
        dut.ui_in.value = 0x04 | (i & 0x03) | ((i * 37) & 0xF8)
        await ClockCycles(dut.clk, 1)
    t._set(sck=0, copi=0, csn=1)
    await ClockCycles(dut.clk, 4)
    st = await t.status()
    assert not bit(st, ST_DISP) and not bit(st, ST_BUSY) and not bit(st, ST_STALE), f"{st:#06x}"
    assert not bit(st, ST_FRAME)
    assert (await t.read(A_ID))[0] == ID_V3


@cocotb.test()
async def test_reg_margin_pins_are_log_scaled(dut):
    """uio_out[7:4] in the register personality is 1 + floor(log2(margin)).
    Cross-checked against the full 32-bit margin read from RESULT."""
    t = await start(dut)
    for desc in (SMALL, LARGE):
        st, r = await t.dispatch(desc)
        m = r["margin"]
        exp = 0 if m == 0 else min(15, m.bit_length())
        got = (int(dut.uio_out.value) >> 4) & 0xF
        dut._log.info(f"margin {m} -> nibble {got}")
        assert got == exp, f"margin {m}: nibble {got}, expected {exp}"
        await t.comp(r["tag"])
