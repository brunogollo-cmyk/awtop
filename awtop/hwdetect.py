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

"""Hardware discovery for Allwinner (sunxi) SoCs, notably the T527 (sun55iw3).

Everything here is discovered at runtime instead of hardcoded, so the same tool
works across sun55iw3 (T527), sun60iw2 (A733) and friends. Each probe degrades
gracefully: an inaccessible node returns None/empty rather than raising.
"""

import contextlib
import glob
import os
import re
import subprocess

DEVFREQ_ROOT = "/sys/class/devfreq"
THERMAL_ROOT = "/sys/class/thermal"
VIPLITE_DEBUG = "/sys/kernel/debug/viplite"
DRM_ROOT = "/sys/class/drm"
CPU_ROOT = "/sys/devices/system/cpu"


def _read(path):
    """Read a sysfs/debugfs file, returning None on any failure."""
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _read_int(path):
    raw = _read(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# --- Board / SoC identity -------------------------------------------------


def get_board_name():
    """Full board model string from the device tree."""
    for p in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        data = _read(p)
        if data:
            model = data.rstrip("\x00").strip()
            if model:
                return model
    return "Unknown Board"


#: sunxi SoC code -> marketing name. The device tree on these boards only
#: exposes the sunxxwY code, so the retail name has to be mapped explicitly.
_SOC_NAMES = {
    "sun50iw9": "H616",
    "sun50iw10": "H618",
    "sun55iw1": "T527",
    "sun55iw2": "T527",
    "sun55iw3": "T527",
    "sun60iw1": "A523",
    "sun60iw2": "A733",
}


def get_soc_family():
    """Marketing SoC name, e.g. 'T527' for sun55iw3 (Orange Pi 4A)."""
    code = get_soc_code()
    if code in _SOC_NAMES:
        return _SOC_NAMES[code]
    for p in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        data = _read(p)
        if not data:
            continue
        blob = data.rstrip("\x00")
        m = re.search(r"\b([AT])\s?(\d{3,4})\b", blob, re.IGNORECASE)
        if m:
            return f"{m.group(1).upper()}{m.group(2)}"
    return "Allwinner"


def get_soc_code():
    """Kernel-level SoC code such as 'sun55iw3'."""
    for p in (
        "/proc/device-tree/compatible",
        "/sys/firmware/devicetree/base/compatible",
    ):
        data = _read(p)
        if not data:
            continue
        for token in data.replace("\x00", ",").split(","):
            token = token.strip()
            m = re.fullmatch(r"(sun\d+iw\d+)p?\d*", token)
            if m:
                return m.group(1)
    return "sunxx"


# --- CPU ------------------------------------------------------------------


def get_cpu_count():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def get_cpu_part():
    """ARM part number, e.g. 0xd05 for Cortex-A55."""
    raw = _read("/proc/cpuinfo")
    if raw:
        m = re.search(r"^CPU part\s*:\s*(0x[0-9a-fA-F]+)", raw, re.MULTILINE)
        if m:
            return m.group(1)
    return None


#: ARM implementer/part -> marketing core name
_ARM_CORES = {
    ("0x41", "0xd03"): "Cortex-A53",
    ("0x41", "0xd04"): "Cortex-A35",
    ("0x41", "0xd05"): "Cortex-A55",
    ("0x41", "0xd07"): "Cortex-A57",
    ("0x41", "0xd08"): "Cortex-A72",
    ("0x41", "0xd09"): "Cortex-A73",
    ("0x41", "0xd0b"): "Cortex-A76",
    ("0x41", "0xd0c"): "Cortex-A77",
    ("0x41", "0xd0d"): "Cortex-A76AE",
    ("0x41", "0xd46"): "Cortex-A510",
    ("0x41", "0xd47"): "Cortex-A710",
    ("0x41", "0xd48"): "Cortex-A715",
}


def get_cpu_name():
    """Best-effort core name for the SoC's big cluster."""
    raw = _read("/proc/cpuinfo")
    if not raw:
        return None
    implementer = re.search(r"^CPU implementer\s*:\s*(0x[0-9a-fA-F]+)", raw, re.MULTILINE)
    part = re.search(r"^CPU part\s*:\s*(0x[0-9a-fA-F]+)", raw, re.MULTILINE)
    if not (implementer and part):
        return None
    key = (implementer.group(1).lower(), part.group(1).lower())
    return _ARM_CORES.get(key)


def get_cpufreq_policies():
    """List of policy directories, ordered by cpu number."""
    policies = []
    for path in glob.glob(f"{CPU_ROOT}/cpufreq/policy*"):
        m = re.search(r"policy(\d+)$", path)
        if m:
            policies.append((int(m.group(1)), path))
    policies.sort()
    return [p for _, p in policies]


def _hz(value):
    """Normalise a cpufreq value to Hz.

    The sunxi cpufreq-dt driver reports scaling_cur_freq in kHz while the
    cpufreq core contract is Hz, so anything under 10MHz is treated as kHz.
    """
    if not value:
        return None
    return value * 1000 if value < 10_000_000 else value


def get_policy_info(policy_path):
    """Cur/min/max frequency (Hz), governor and cpu count for one cpufreq policy.

    The sunxi cpufreq-dt driver reports scaling_min_freq as 0, so the cpuinfo
    range is used as the floor when that happens.
    """
    min_freq = _read_int(f"{policy_path}/scaling_min_freq") or _read_int(
        f"{policy_path}/cpuinfo_min_freq"
    )
    return {
        "policy": os.path.basename(policy_path),
        "cur_freq": _hz(_read_int(f"{policy_path}/scaling_cur_freq")),
        "min_freq": _hz(min_freq),
        "max_freq": _hz(_read_int(f"{policy_path}/scaling_max_freq")),
        "governor": _read(f"{policy_path}/scaling_governor"),
        "cpus": sorted(_cpus_for_policy(policy_path)),
    }


def _cpus_for_policy(policy_path):
    """CPU numbers attached to a cpufreq policy (clusters share one policy)."""
    cpus = set()
    for cpu_dir in glob.glob(f"{CPU_ROOT}/cpu[0-9]*"):
        link = os.path.realpath(f"{cpu_dir}/cpufreq")
        if link == os.path.realpath(policy_path):
            m = re.search(r"cpu(\d+)$", cpu_dir)
            if m:
                cpus.add(int(m.group(1)))
    return cpus


def get_cpu_frequencies():
    """Current frequency in MHz for every online CPU, 0 when unavailable.

    The T527 has 8 cores but only two cpufreq policies (0-3 and 4-7), so this
    falls back to the policy frequency rather than assuming a per-cpu node.
    """
    n = get_cpu_count()
    freqs = []
    for cpu_id in range(n):
        raw = _read_int(f"{CPU_ROOT}/cpu{cpu_id}/cpufreq/scaling_cur_freq")
        if raw is None:
            policy = _policy_for_cpu(cpu_id)
            raw = _read_int(f"{policy}/scaling_cur_freq") if policy else None
        hz = _hz(raw)
        freqs.append(hz // 1_000_000 if hz else 0)
    return freqs


def _policy_for_cpu(cpu_id):
    link = os.path.realpath(f"{CPU_ROOT}/cpu{cpu_id}/cpufreq")
    return link if os.path.isdir(link) else None


def get_cluster_summary():
    """Human-readable cluster layout, e.g. '4x A55 @1.42GHz + 4x A55 @1.80GHz'."""
    groups = []
    for policy_path in get_cpufreq_policies():
        info = get_policy_info(policy_path)
        if not info["cpus"]:
            continue
        count = len(info["cpus"])
        if info["max_freq"]:
            speed = f"{info['max_freq'] / 1e9:.2f}GHz"
        else:
            speed = "?"
        groups.append((count, speed))
    if not groups:
        return None
    parts = [f"{c}x {g}" for c, g in groups]
    name = get_cpu_name()
    prefix = f"{name} " if name else ""
    return prefix + " + ".join(parts)


# --- devfreq (GPU / NPU / DDR) -------------------------------------------


def list_devfreq():
    """All devfreq nodes as (name, path) pairs, sorted by name."""
    out = []
    for path in sorted(glob.glob(f"{DEVFREQ_ROOT}/*")):
        name = _read(f"{path}/name")
        if name:
            out.append((name, path))
    return out


def get_devfreq_info(path):
    """Current/min/max frequency, governor and busytime-based load for a node."""
    cur = _read_int(f"{path}/cur_freq")
    min_f = _read_int(f"{path}/min_freq")
    max_f = _read_int(f"{path}/max_freq")
    info = {
        "name": _read(f"{path}/name"),
        "cur_freq": cur,
        "min_freq": min_f,
        "max_freq": max_f,
        "governor": _read(f"{path}/governor"),
        "load": None,
    }
    info["load"] = _devfreq_load(path, cur, min_f)
    return info


def _devfreq_load(path, cur, min_f):
    """Derive a utilisation percentage from the devfreq busy time.

    The T527 GPU/DDR nodes do not export the `load` attribute, so occupancy is
    approximated from how long the device has sat at its top frequency.
    Returns None when no signal is available.
    """
    max_f = _read_int(f"{path}/max_freq")
    if cur is None or min_f is None or max_f is None or max_f <= min_f:
        return None
    if cur <= min_f:
        return 0.0
    span = (cur - min_f) / (max_f - min_f)
    return max(0.0, min(100.0, span * 100.0))


def _devfreq_busy_pct(path):
    """Percentage of time the device spent running at its top frequency.

    `trans_stat` is a transition matrix: every row is a source frequency
    followed by one time value per target frequency, and the rows are ordered
    by ascending frequency. Summing the column of the highest frequency gives
    the time actually spent at the top clock, which is the closest thing to a
    busy signal on drivers that do not export `load`.

    The column list is derived from the row labels rather than the header
    because some sunxi nodes (the DMC controller) print the header frequencies
    without separators, fusing two of them into one unusable token.
    """
    raw = _read(f"{path}/trans_stat")
    if not raw:
        return None

    rows = []
    for line in raw.splitlines():
        m = re.match(r"^\s*\*?\s*(\d+):(.*)$", line)
        if not m:
            continue
        rows.append((int(m.group(1)), m.group(2)))
    if not rows:
        return None

    freqs = [freq for freq, _ in rows]
    top = max(freqs)
    top_col = freqs.index(top)

    busy = total = 0
    for _, body in rows:
        values = [int(v) for v in body.split()]
        # Trailing totals (time, transitions) are not per-frequency buckets.
        buckets = values[: len(freqs)]
        if len(buckets) <= top_col:
            continue
        busy += buckets[top_col]
        total += sum(buckets)
    if not total:
        return None
    return busy / total * 100.0


# --- GPU ------------------------------------------------------------------


def get_gpu_path():
    """Locate the GPU devfreq node, whichever SoC we are on."""
    for name, path in list_devfreq():
        if "gpu" in name.lower():
            return path
    return None


def get_gpu_driver():
    """GPU driver name (panfrost/panthor/mali).

    The board exposes card0 as the sunxi-drm display output and card1 as the
    actual Mali GPU, so we resolve the card that sits under the GPU platform
    device rather than taking the first one.
    """
    gpu_dev = os.path.realpath(f"{DEVFREQ_ROOT}/{os.path.basename(get_gpu_path() or '')}/device")
    for card in sorted(glob.glob(f"{DRM_ROOT}/card[0-9]*")):
        dev = os.path.realpath(f"{card}/device")
        if gpu_dev and dev == gpu_dev:
            drv = None
            with contextlib.suppress(OSError):
                drv = os.path.basename(os.readlink(f"{card}/device/driver"))
            if drv:
                return drv
    # Fallback: any card whose driver looks like a GPU driver.
    for card in sorted(glob.glob(f"{DRM_ROOT}/card[0-9]*")):
        drv = None
        with contextlib.suppress(OSError):
            drv = os.path.basename(os.readlink(f"{card}/device/driver"))
        if drv and drv in ("panfrost", "panthor", "mali", "lima", "msm"):
            return drv
    return None


def get_gpu_renderer():
    """GL renderer string, used to confirm which Mali core is present."""
    try:
        out = subprocess.run(
            ["glxinfo", "-B"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"OpenGL renderer string:\s*(.+)", out.stdout)
    return m.group(1).strip() if m else None


def get_gpu_usage():
    """GPU busy percentage, or None when the driver exposes no such metric.

    `trans_stat` is preferred because it is cumulative and time-weighted, so it
    does not flicker between refreshes the way a single frequency sample does.
    """
    path = get_gpu_path()
    if not path:
        return None
    busy = _devfreq_busy_pct(path)
    if busy is not None:
        return busy
    return get_devfreq_info(path)["load"]


def get_gpu_frequency():
    """GPU frequency in MHz."""
    path = get_gpu_path()
    if not path:
        return None
    cur = _read_int(f"{path}/cur_freq")
    return cur // 1_000_000 if cur else None


# --- NPU (Vivante VIPLite / viplite) --------------------------------------


def get_npu_driver_version():
    """VIPLite driver version from debugfs, else from the boot kernel log."""
    for p in (f"{VIPLITE_DEBUG}/version", f"{VIPLITE_DEBUG}/driver_version"):
        raw = _read(p)
        if raw:
            m = re.search(r"version[:\s]+(\S+)", raw, re.IGNORECASE)
            return m.group(1) if m else raw.strip()
    return _viplite_version_from_klog()


def _viplite_version_from_klog():
    """Fall back to the VIPLite banner the kernel logs at boot."""
    for cmd in (
        ["journalctl", "-k", "-b", "--no-pager"],
        ["dmesg"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"VIPLite driver version (\S+)", out.stdout or "")
        if m:
            return m.group(1)
    return "Not Detected"


def get_npu_chip():
    """NPU generation, e.g. 'VF3' (VIP9000 series) as reported at boot."""
    for cmd in (
        ["journalctl", "-k", "-b", "--no-pager"],
        ["dmesg"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"NPU Use (\S+?), use freq", out.stdout or "")
        if m:
            return m.group(1)
    return None


def get_npu_load():
    """Per-core NPU utilisation.

    Prefers `core_loading` in debugfs, which reports one line per core. Falls
    back to the older `load` node when present. Returns [] when neither is
    readable, which makes the caller hide the NPU panel.
    """
    raw = _read(f"{VIPLITE_DEBUG}/core_loading")
    if raw:
        loads = _parse_core_loading(raw)
        if loads:
            return loads
    raw = _read(f"{VIPLITE_DEBUG}/load")
    if raw:
        return [int(p) for p in re.findall(r"(\d+)\s*%", raw)]
    return []


def _parse_core_loading(text):
    """Parse the viplite `core_loading` debugfs output into percentages.

    Handles the layouts seen across VIPLite driver generations:
      core 0 loading = 12%
      Core0:  12%
      core_0: 12 34 56      (per-scenario columns, first column is taken)
    Summary lines are ignored so a single-core NPU still reports one value.
    Anything unrecognised yields [] so the caller can fall back.
    """
    loads = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if re.search(r"total|average|avg\b", line, re.IGNORECASE):
            continue
        m = re.search(r"(\d+)\s*%", line)
        if m:
            loads.append(min(100, int(m.group(1))))
            continue
        # No percent sign: only trust lines that actually name a core, so a
        # stray version string cannot be mistaken for a load value.
        if not re.search(r"core", line, re.IGNORECASE):
            continue
        m = re.search(r"core\S*[\s:=]+(\d+)", line, re.IGNORECASE)
        if m:
            loads.append(min(100, int(m.group(1))))
    return loads


def get_npu_frequency():
    """NPU clock in MHz.

    VIPLite on the T527 pins the NPU to a fixed 696MHz and exposes no devfreq
    node, so the value is recovered from the boot log when sysfs is silent.
    """
    path = _find_npu_devfreq()
    if path:
        cur = _read_int(f"{path}/cur_freq")
        if cur:
            return cur // 1_000_000
    return _npu_freq_from_klog()


def _npu_freq_from_klog():
    for cmd in (
        ["journalctl", "-k", "-b", "--no-pager"],
        ["dmesg"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"NPU Use \S+?, use freq (\d+)", out.stdout or "")
        if m:
            return int(m.group(1))
    return None


def _find_npu_devfreq():
    for name, path in list_devfreq():
        if "npu" in name.lower():
            return path
    return None


def get_npu_memory():
    """Video memory the vipcore driver carved out, in bytes, or None."""
    for cmd in (
        ["journalctl", "-k", "-b", "--no-pager"],
        ["dmesg"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"video memory heap size.*?only can allocate (\d+)M byte", out.stdout or "")
        if m:
            return int(m.group(1)) * 1024 * 1024
        m = re.search(r"vip_memsize=(0x[0-9a-fA-F]+)", out.stdout or "")
        if m:
            return int(m.group(1), 16)
    return None


def has_npu():
    """True when a vipcore NPU is present, even if it is idle."""
    if get_npu_load():
        return True
    return get_npu_driver_version() != "Not Detected"


# --- DDR / memory controller (DMC) ----------------------------------------


def get_dmc_path():
    """Locate the DDR (dmcfreq) devfreq node."""
    for name, path in list_devfreq():
        if "dmc" in name.lower() or "ddr" in name.lower():
            return path
    return None


def get_dmc_info():
    """DDR controller frequency range and governor.

    Note that this board pins the DMC to the `performance` governor, so there
    is no meaningful busy signal to report: trans_stat stays empty because the
    clock never changes.
    """
    path = get_dmc_path()
    if not path:
        return None
    return get_devfreq_info(path)


# --- zram -----------------------------------------------------------------


def get_zram_stats():
    """(used, total) bytes for every zram device, summing swap-like sizes.

    The T527 images ship both zram0 (the real swap) and a small zram1, so both
    are aggregated instead of only reading zram0 like rk tooling does.
    """
    used = total = 0
    found = False
    for mm_stat in sorted(glob.glob("/sys/block/zram*/mm_stat")):
        raw = _read(mm_stat)
        if not raw:
            continue
        parts = raw.split()
        if len(parts) < 4:
            continue
        # orig_data_size, compr_data_size, mem_used, mem_limit
        try:
            used += int(parts[2])
            total += int(parts[3])
        except ValueError:
            continue
        found = True
    return (used, total) if found else (0, 0)
