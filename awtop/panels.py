#
# awtop - Allwinner `top`-like Tool
# Copyright (C) 2025  Emmanuel Cortes. All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Rich panels rendering the hardware state of an Allwinner board."""

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table

from . import hwdetect
from . import sysinfo


def build_cpu_panel():
    """One bar per core, with frequency taken from its cpufreq cluster."""
    usage = sysinfo.get_cpu_load()
    freqs = hwdetect.get_cpu_frequencies()

    table = Table.grid(expand=True)
    table.add_column()
    for cpu_id, u in enumerate(usage):
        mhz = freqs[cpu_id] if cpu_id < len(freqs) else 0
        bar = Progress(
            TextColumn(f"CPU {cpu_id}"),
            BarColumn(bar_width=None),
            TextColumn(f"{u:>3.0f}% {mhz:>4d} MHz"),
            expand=True,
        )
        bar.add_task("", total=100, completed=u)
        table.add_row(bar)

    return Panel(
        table, title="CPU", padding=(1, 2), border_style="cyan", box=box.ROUNDED
    )


def build_mem_panel():
    """RAM / swap / zram usage with a detail grid underneath."""
    vm, sm = sysinfo.get_mem_info()
    cached = sysinfo.human_bytes(getattr(vm, "cached", 0))
    shared = sysinfo.human_bytes(getattr(vm, "shared", 0))
    free = sysinfo.human_bytes(vm.available)
    total = sysinfo.human_bytes(vm.total)
    ram_used = sysinfo.human_bytes(vm.used)
    ram_info = f"{sysinfo.human_bytes(vm.used + vm.cached)} / {total}"
    swap_info = f"{sysinfo.human_bytes(sm.used)} / {sysinfo.human_bytes(sm.total)}"

    zused, ztot = hwdetect.get_zram_stats()
    zram_info = f"{sysinfo.human_bytes(zused)} / {sysinfo.human_bytes(ztot)}"
    zram_pct = (zused / ztot * 100) if ztot > 0 else 0.0

    details = Table.grid(expand=True)
    details.add_column(justify="left")
    details.add_column(justify="center")
    details.add_column(justify="right")
    details.add_row(
        f"[bold]Total:[/bold] {total}",
        f"[bold]Free:[/bold] {free}",
        f"[bold]Used:[/bold] {ram_used}",
    )
    details.add_row(f"[bold]Cache:[/bold] {cached}", f"[bold]Shared:[/bold] {shared}")

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(bar_width=None),
        TextColumn(
            "{task.percentage:>3.0f}% [dim]| {task.fields[info]:>16}", justify="right"
        ),
        expand=True,
    )
    progress.add_task("RAM", total=100, completed=vm.percent, info=ram_info)
    progress.add_task("Swap", total=100, completed=sm.percent, info=swap_info)
    progress.add_task("ZRAM", total=100, completed=zram_pct, info=zram_info)

    return Panel(
        Group(progress, details),
        title="Memory",
        padding=(0, 1),
        border_style="cyan",
        box=box.ROUNDED,
    )


def build_gpu_panel():
    """GPU utilisation, frequency and governor from the devfreq node."""
    usage = hwdetect.get_gpu_usage()
    freq = hwdetect.get_gpu_frequency()
    path = hwdetect.get_gpu_path()
    governor = hwdetect._read(f"{path}/governor") if path else None

    if usage is None:
        return Panel(
            f"GPU utilisation unavailable\n[dim]driver: "
            f"{hwdetect.get_gpu_driver() or 'unknown'}[/dim]",
            title="GPU",
            box=box.ROUNDED,
            border_style="green",
        )

    freq_str = f" {freq} MHz" if freq is not None else ""
    progress = Progress(
        TextColumn("GPU"),
        BarColumn(bar_width=None),
        TextColumn(f"{usage:.0f}%{freq_str}"),
        expand=True,
    )
    progress.add_task("", total=100, completed=usage)
    return Panel(
        Group(progress, _subtle(f"governor: {governor}" if governor else None)),
        title="GPU",
        padding=(0, 1),
        border_style="green",
        box=box.ROUNDED,
    )


def build_npu_panel():
    """Per-core NPU load, chip generation and VIPLite driver version.

    On the T527 the vipcore driver exposes a single core; the panel scales to
    whatever `core_loading` reports so other sunxi boards show all cores.
    """
    loads = hwdetect.get_npu_load()
    chip = hwdetect.get_npu_chip()
    driver = hwdetect.get_npu_driver_version()
    freq = hwdetect.get_npu_frequency()

    if not loads:
        return Panel(
            f"NPU idle (no core_loading)\n[dim]{chip or ''} VIPLite {driver}[/dim]",
            title="NPU",
            box=box.ROUNDED,
            border_style="green",
        )

    freq_str = f" {freq:>4d} MHz" if freq else ""
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(bar_width=None),
        TextColumn(f"{{task.percentage:>3.0f}}%{freq_str}"),
        expand=True,
    )
    for i, val in enumerate(loads):
        progress.add_task(f"NPU Core {i}", total=100, completed=val)

    footer = f"{chip} VIPLite {driver}" if chip else f"VIPLite {driver}"
    return Panel(
        Group(progress, _subtle(footer)),
        title="NPU",
        padding=(0, 1),
        border_style="green",
        box=box.ROUNDED,
    )


def build_dmc_panel():
    """DDR memory-controller frequency and governor.

    No utilisation bar is drawn here on purpose: this board runs the DMC under
    the `performance` governor, so it simply sits at its maximum clock and any
    bar derived from that would always read 100% regardless of real activity.
    """
    info = hwdetect.get_dmc_info()
    if not info:
        return Panel("DDR controller not exposed", title="DDR", box=box.ROUNDED)

    cur = info["cur_freq"]
    lo = info["min_freq"]
    hi = info["max_freq"]
    freq_str = f"{cur // 1_000_000} MHz" if cur else "unknown"
    range_str = (
        f"{lo // 1_000_000}-{hi // 1_000_000} MHz"
        if lo and hi and lo != hi
        else freq_str
    )

    details = Table.grid(expand=True)
    details.add_column(justify="left")
    details.add_column(justify="right")
    details.add_row("[bold]Frequency:[/bold] " + freq_str, f"[dim]{range_str}[/dim]")
    if info["governor"]:
        details.add_row("[bold]Governor:[/bold] " + info["governor"], "")

    return Panel(
        details,
        title="DDR",
        padding=(0, 1),
        border_style="green",
        box=box.ROUNDED,
    )


def build_sys_panel():
    """Static board identification and driver/runtime versions."""
    board = hwdetect.get_board_name()
    soc = hwdetect.get_soc_family()
    soc_code = hwdetect.get_soc_code()

    table = Table.grid(expand=True)
    table.add_column()
    table.add_column(justify="right")

    # The device tree on these boards only carries the sunxxwY code, which the
    # SoC row already shows, so fall back to a real board name here.
    if board.lower().startswith("sun") or board == "Unknown Board":
        board = f"sunxi {soc}"
    table.add_row("[bold]Board[/bold]", f"[italic]{board}[/italic]")
    table.add_row("[bold]SoC[/bold]", f"{soc} ({soc_code})")

    clusters = hwdetect.get_cluster_summary()
    if clusters:
        table.add_row("[bold]CPU[/bold]", clusters)
    part = hwdetect.get_cpu_part()
    if part:
        table.add_row("[bold]CPU part[/bold]", f"0x{int(part, 16):03d}")

    gov = sysinfo.get_cpu_governors()
    if gov:
        table.add_row("[bold]CPU governor[/bold]", gov)

    npu = hwdetect.get_npu_driver_version()
    chip = hwdetect.get_npu_chip()
    npu_label = f"NPU Driver ({chip})" if chip else "NPU Driver"
    table.add_row(npu_label, npu)

    mem = hwdetect.get_npu_memory()
    if mem:
        table.add_row("NPU memory", sysinfo.human_bytes(mem))

    gpu_drv = hwdetect.get_gpu_driver()
    if gpu_drv:
        table.add_row("GPU driver", gpu_drv)

    return Panel(
        table,
        title="SYS",
        padding=(0, 1),
        border_style="red",
        box=box.ROUNDED,
    )


def build_io_table():
    """Disk and per-adapter network throughput."""
    read_rate, write_rate = sysinfo.get_io_rates()
    tbl = Table(title="I/O", box=box.ROUNDED, expand=True, padding=(0, 1))
    tbl.add_column("Metric", style="cyan")
    tbl.add_column("Read/RX", justify="right")
    tbl.add_column("Write/TX", justify="right")
    tbl.add_row("Disk", f"{sysinfo.human_bytes(read_rate)}/s",
                f"{sysinfo.human_bytes(write_rate)}/s")
    for name, rx, tx in sysinfo.get_net_rates():
        tbl.add_row(
            name,
            f"{sysinfo.human_bytes(rx)}/s",
            f"{sysinfo.human_bytes(tx)}/s",
        )
    return tbl


def build_thermal_table():
    tbl = Table(
        title="Temperatures", box=box.ROUNDED, expand=True, padding=(0, 1)
    )
    tbl.add_column("Sensor", style="cyan")
    tbl.add_column("Temp", justify="right")
    for name, val in sysinfo.get_thermal():
        tbl.add_row(name, f"{val}°C")
    return tbl


def build_process_panel(sort_mode="cpu_desc"):
    """Process table with the interactive sort mode shown in its title."""
    processes = sysinfo.get_top_processes(count=24, sort_mode=sort_mode)
    sort_display = sysinfo.SORT_MODES.get(sort_mode, ("", "CPU↓"))[1]

    title = f"Sort: [C]PU [M]em [P]ID [N]ame | Current: {sort_display} | [Q]uit"
    table = Table(title=title, box=box.ROUNDED, expand=True, padding=(0, 1))
    table.add_column("PID", style="cyan", justify="right", width=6)
    table.add_column("User", style="white", width=6)
    table.add_column("Name", style="green", width=40)
    table.add_column("CPU%", justify="right", width=6)
    table.add_column("Mem%", justify="right", width=6)

    for proc in processes:
        user = proc["user"]
        user_cell = f"[dim]{user}" if user in ("root", "0") else user
        table.add_row(
            str(proc["pid"]),
            user_cell,
            proc["name"],
            f"{proc['cpu']:.1f}",
            f"{proc['mem']:.1f}",
        )
    return table


def _subtle(text):
    """Render a dim caption, or nothing when there is no text."""
    return Table.grid() if text is None else f"[dim]{text}[/dim]"
