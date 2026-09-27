# awtop

A `top`-like system monitor for **Allwinner (sunxi)** boards, written in Python
with [`rich`](https://github.com/Textualize/rich) and
[`psutil`](https://github.com/giampaolo/psutil).

Developed against an **Orange Pi 4A** — Allwinner **T527** (`sun55iw3`), with a
Vivante **VIP9000 (VF3)** NPU, a **Mali-G57** GPU on `panfrost`, and a DMC
memory controller. Also expected to work on A523 / A733 / H616 / H618 images,
since every peripheral is discovered at runtime rather than hardcoded.

```
╭──────────────────────────────── CPU ─────────────────────────────────╮╭──────────────────────────────── SYS ────────────────────────────────╮
│  CPU 0 ━━━━━━━━━━━━━━━━━━━━━━━━╸                          50% 1416 MHz ││ Board                                                        sunxi T527 │
│  CPU 4 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸             75% 1800 MHz ││ SoC                                                     T527 (sun55iw3) │
╰─────────────────────────────────────────────────────────────────────────╯│ CPU                                  Cortex-A55 4x 1.42GHz + 4x 1.80GHz │
╭──────────────────────────────── Memory ────────────────────────────────╮│ NPU Driver (VF3)                                 1.13.0.0-AW-2023-01-09 │
│ RAM  ━━━━━━━━━━━━━━━━━━━━━━━━━━╸                 63% |  3.8 GB / 3.8 GB ││ NPU memory                                                       4.0 MB │
╰─────────────────────────────────────────────────────────────────────────╯╰─────────────────────────────────────────────────────────────────────────╯
```

## Features

| Panel | Source | Notes |
| --- | --- | --- |
| **CPU** | `psutil` + `cpufreq` | One bar per core. The T527 has 8 cores but only **two** policies (0–3 little, 4–7 big), so each core reports its cluster's clock. |
| **Memory** | `psutil` | RAM / swap / ZRAM, with a detail grid. |
| **GPU** | devfreq `trans_stat` | Busy time at the top clock, clock speed and governor. |
| **NPU** | `/sys/kernel/debug/viplite/core_loading` | Per-core load, chip generation and VIPLite version. |
| **DDR** | devfreq | Memory-controller clock and governor. |
| **I/O** | `psutil` | Disk and per-NIC throughput. |
| **Temperatures** | `psutil` | cpul / cpub / gpu / npu / ddr zones plus the AXP2202 PMIC. |
| **Processes** | `psutil` | Sortable table of the 24 busiest processes. |

### Keys

| Key | Action |
| --- | --- |
| `C` | Sort by CPU (toggles ascending / descending) |
| `M` | Sort by memory |
| `P` | Sort by PID |
| `N` | Sort by process name |
| `Q` / `Esc` | Quit |

## Requirements

- An Allwinner (sunxi) board — tested on T527 / `sun55iw3`
- Python 3.9 or newer
- `python3-psutil` and `python3-rich`

## Installation

### From a clone (recommended)

```sh
git clone https://github.com/<you>/awtop.git
cd awtop
sudo make install
awtop
```

`make install` runs `install.sh`, which copies the package to
`/usr/local/lib/awtop` and drops a launcher at `/usr/local/bin/awtop`.

If a dependency is missing, the installer tells you exactly what to run:

```
Missing dependencies: python3-rich
Install them with: sudo apt install python3-rich
```

So the usual first run is:

```sh
sudo apt install python3-psutil python3-rich
```

### Without installing

The tool runs straight from a checkout:

```sh
git clone https://github.com/<you>/awtop.git
cd awtop
sudo ./awtop.py
```

### Different prefix

Both the Makefile and the script honour `PREFIX`:

```sh
sudo make install PREFIX=/usr
PREFIX=~/.local sudo -E sh install.sh
```

### Uninstall

```sh
sudo make uninstall          # or: sudo ./install.sh --uninstall
```

## Root is required

The NPU's `core_loading` file lives in debugfs, which is root-only. Running
`awtop` as a normal user exits immediately with a clear message rather than
rendering a half-empty dashboard.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pyflakes

make test     # 34 tests, no root required
make lint     # pyflakes
make check    # both
```

The suite runs without root: every hardware probe is fed a fixture instead of
the live sysfs/debugfs tree, including the `trans_stat` matrix format and the
`core_loading` layout variants.

## How the sunxi-specific bits work

**SoC identification.** The device tree on these boards only exposes the
`sunxxwY` code, not the retail name, so `sun55iw3 → T527` is mapped explicitly
in `hwdetect._SOC_NAMES`.

**NPU.** The T527's Vivante NPU has no devfreq node and no sysfs load
attribute. The version, chip generation (`VF3`), clock (696 MHz) and carved-out
video memory are recovered from the VIPLite banner in the kernel log, and the
live load comes from `debugfs/viplite/core_loading`. The parser accepts the
several layouts used across VIPLite driver generations and skips summary lines
so a single-core NPU still reports one value.

**GPU load.** Mali on sunxi exposes no `busy_time`/`idle_time` file like the
Mali driver on Rockchip does, and the devfreq node has no `load` attribute.
Utilisation is therefore derived from `trans_stat` — the fraction of time spent
at the highest available clock. This is an approximation, not a hardware
counter, and it reads 0% on a GPU that is busy but throttled low.

**DDR.** The DMC runs under the `performance` governor and never leaves its
maximum clock, so no utilisation bar is drawn; it would always read 100%.

**CPU frequency units.** The sunxi `cpufreq-dt` driver reports
`scaling_cur_freq` in **kHz** even though the cpufreq contract is Hz, and
reports `scaling_min_freq` as 0. `hwdetect._hz()` normalises the unit and
`cpuinfo_min_freq` is used as the floor.

**ZRAM.** This image ships both `zram0` (the real swap) and a small `zram1`;
both are summed rather than only reading `zram0`.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
