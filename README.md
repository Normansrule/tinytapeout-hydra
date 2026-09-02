# TT-A: HYDRA-130 Mathematical Operation MUX

TinyTapeout spinout of the dispatch unit from HYDRA-130.

## Build

`src/project.v` is generated, not hand-written. Regenerate it after any RTL
change:

```bash
cd ../..                       # hydra project root
sv2v rtl/mom/mom_pkg.sv rtl/mom/mom_features.sv rtl/mom/mom_param_rom.sv \
     rtl/mom/mom_cost_engine.sv rtl/mom/mom_calibrate.sv rtl/mom/mom_select.sv \
     rtl/mom/mom_scoreboard.sv rtl/mom/mom_top.sv \
     tt_tiles/tt_um_hydra_mom/src/tt_um_hydra_mom.sv \
     > tt_tiles/tt_um_hydra_mom/src/project.v
```

`project.v` must live at exactly `src/project.v`. That path has bitten this
author before.

## Before ordering tiles

`tiles: "3x4"` in `info.yaml` is an estimate from generic-gate counts, not a
measurement. Run the harden first and read the real utilization:

```bash
./tt/tt_tool.py --create-user-config
./tt/tt_tool.py --harden
python3 -c "import json; m=json.load(open('runs/wokwi/final/metrics.json')); \
  print('util', m['design__instance__utilization'], \
        'die', m['design__die__area'])"
```

If utilization comes in well under 60%, drop to `4x2` and save four tiles.
Change `tiles` in `info.yaml` and re-run `--create-user-config`. **Do not
hand-edit `src/config.json`.**

## Configuration differences from the full HYDRA-130 MOM

| Parameter | HYDRA-130 | TT-A | Why |
|---|---:|---:|---|
| `NTAG` | 16 | 8 | The serial interface never gets more than a few descriptors in flight; 16 tags would buy nothing and cost ~450 flops |
| `QMAX` | 8 | 4 | Same reasoning |
| Parameter ROM CSR | writable | tied to reset defaults | Writing 43 bits per row would need a second serial channel, and the defaults are what the verification suite ran against |
| Calibration | configurable | always enabled | Watching the loop converge on real hardware is the point of the tile |

Everything else is the full design, unmodified.
