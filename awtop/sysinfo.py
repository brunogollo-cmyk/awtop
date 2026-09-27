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

"""System-level metrics: CPU, memory, temperatures, I/O and processes."""

import contextlib
import math
import time

import psutil

from . import hwdetect

#: Per-adapter network deltas: {adapter: (bytes_recv, bytes_sent, timestamp)}
PREV_ADAPTERS = {}
PREV_DISK = None
PREV_TIME = None


def human_bytes(val):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} PB"


def get_cpu_load():
    """Per-core CPU utilisation percentage."""
    return psutil.cpu_percent(percpu=True, interval=0.1)


def get_cpu_freq_range():
    """(min_mhz, max_mhz) across every cpufreq policy."""
    mins, maxs = [], []
    for policy in hwdetect.get_cpufreq_policies():
        info = hwdetect.get_policy_info(policy)
        if info["min_freq"]:
            mins.append(info["min_freq"])
        if info["max_freq"]:
            maxs.append(info["max_freq"])
    if not mins or not maxs:
        return 0, 0
    return min(mins) // 1_000_000, max(maxs) // 1_000_000


def get_cpu_governors():
    """Governor of each cluster, joined for display."""
    govs = []
    for policy in hwdetect.get_cpufreq_policies():
        info = hwdetect.get_policy_info(policy)
        if info["governor"]:
            govs.append(info["governor"])
    return ", ".join(dict.fromkeys(govs)) or None


def get_mem_info():
    return psutil.virtual_memory(), psutil.swap_memory()


def get_thermal():
    """(label, celsius) for every readable thermal zone.

    The T527 exposes cpul/cpub/gpu/npu/ddr zones plus the AXP2202 PMIC, so all
    of them are shown rather than just the CPU.
    """
    temps = []
    with contextlib.suppress(Exception):
        for name, entries in psutil.sensors_temperatures().items():
            if not entries or entries[0].current is None:
                continue
            label = name.replace("_thermal_zone", "")
            temps.append((label, math.floor(entries[0].current)))
    return temps


def get_io_rates():
    """(disk_read_bps, disk_write_bps) computed against the previous call."""
    global PREV_DISK, PREV_TIME
    now = time.time()
    disk = psutil.disk_io_counters()
    if disk is None:
        return 0.0, 0.0
    if PREV_TIME:
        interval = now - PREV_TIME
        if interval > 0:
            read_rate = (disk.read_bytes - PREV_DISK.read_bytes) / interval
            write_rate = (disk.write_bytes - PREV_DISK.write_bytes) / interval
        else:
            read_rate = write_rate = 0.0
    else:
        read_rate = write_rate = 0.0
    PREV_DISK, PREV_TIME = disk, now
    return read_rate, write_rate


#: Loopback and unnumbered/tunnel interfaces that carry no useful traffic.
_NET_NOISE_PREFIXES = ("lo", "ip6_", "ip_vti", "ip6tnl", "ip_tunnel", "sit")


def get_net_rates():
    """(adapter_name, rx_bps, tx_bps) for every NIC, computed against last call.

    Loopback and tunnel interfaces are skipped; they are always idle and would
    otherwise push the real NICs off the bottom of the table.
    """
    adapters = psutil.net_io_counters(pernic=True)
    now = time.time()
    rates = []
    for name, stats in sorted(adapters.items()):
        if name.startswith(_NET_NOISE_PREFIXES):
            continue
        prev = PREV_ADAPTERS.get(name)
        PREV_ADAPTERS[name] = (stats.bytes_recv, stats.bytes_sent, now)
        if prev and now > prev[2]:
            interval = now - prev[2]
            rates.append(
                (
                    name,
                    (stats.bytes_recv - prev[0]) / interval,
                    (stats.bytes_sent - prev[1]) / interval,
                )
            )
        else:
            rates.append((name, 0.0, 0.0))
    return rates


#: Sort modes for the process table, mapped to their key and display label.
SORT_MODES = {
    "cpu_desc": (lambda p: p["cpu"], "CPU↓"),
    "cpu_asc": (lambda p: p["cpu"], "CPU↑"),
    "mem_desc": (lambda p: p["mem"], "Mem↓"),
    "mem_asc": (lambda p: p["mem"], "Mem↑"),
    "pid_desc": (lambda p: p["pid"], "PID↓"),
    "pid_asc": (lambda p: p["pid"], "PID↑"),
    "name_desc": (lambda p: p["name"].lower(), "Name↓"),
    "name_asc": (lambda p: p["name"].lower(), "Name↑"),
}


def get_top_processes(count=5, sort_mode="cpu_desc"):
    """Top processes sorted by the requested mode."""
    processes = []
    for proc in psutil.process_iter(
        attrs=["pid", "name", "username", "cpu_percent", "memory_percent"]
    ):
        try:
            info = proc.info
            if info.get("cpu_percent") is None:
                continue
            processes.append(
                {
                    "pid": info["pid"],
                    "name": info["name"] or "",
                    "user": info["username"] or "unknown",
                    "cpu": info["cpu_percent"] or 0.0,
                    "mem": info["memory_percent"] or 0.0,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue

    key, _ = SORT_MODES.get(sort_mode, SORT_MODES["cpu_desc"])
    processes.sort(key=key, reverse=sort_mode.endswith("_desc"))
    return processes[:count]
