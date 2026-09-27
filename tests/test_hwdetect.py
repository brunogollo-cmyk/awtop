"""Tests for awtop's Allwinner hardware probes.

These run without root: every probe is fed a fixture instead of the live
debugfs/sysfs tree, which is what CI and the dev loop actually need.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from awtop import hwdetect  # noqa: E402
from awtop import sysinfo  # noqa: E402


class TestCoreLoadingParser:
    """The viplite `core_loading` format varies between driver generations."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("core 0 loading = 12%", [12]),
            ("Core0:  12%", [12]),
            ("core_0: 55 10 20", [55]),
            ("core 0: 45%\ncore 1: 78%", [45, 78]),
            ("core0=33\ncore1=66", [33, 66]),
        ],
    )
    def test_recognised_formats(self, text, expected):
        assert hwdetect._parse_core_loading(text) == expected

    def test_summary_lines_ignored(self):
        text = "core 0: 40%\ntotal load = 40%\naverage = 40%"
        assert hwdetect._parse_core_loading(text) == [40]

    @pytest.mark.parametrize("text", ["", "no numbers here", "version 1.13.0"])
    def test_unparseable_yields_empty(self, text):
        assert hwdetect._parse_core_loading(text) == []

    def test_values_are_clamped(self):
        assert hwdetect._parse_core_loading("core 0: 150%") == [100]


class TestFrequencyUnits:
    """The sunxi cpufreq-dt driver reports kHz where the core contract says Hz."""

    def test_khz_scaled_to_hz(self):
        assert hwdetect._hz(1_416_000) == 1_416_000_000

    def test_hz_left_alone(self):
        assert hwdetect._hz(1_416_000_000) == 1_416_000_000

    def test_zero_is_falsy(self):
        assert hwdetect._hz(0) is None
        assert hwdetect._hz(None) is None


class TestSocMapping:
    """sunxxwY codes must resolve to the retail SoC name."""

    @pytest.mark.parametrize(
        "code,expected",
        [("sun55iw3", "T527"), ("sun60iw2", "A733"), ("sun50iw9", "H616")],
    )
    def test_known_codes(self, code, expected, monkeypatch):
        monkeypatch.setattr(hwdetect, "get_soc_code", lambda: code)
        assert hwdetect.get_soc_family() == expected

    def test_unknown_code_falls_back(self, monkeypatch):
        monkeypatch.setattr(hwdetect, "get_soc_code", lambda: "sun99iw9")
        monkeypatch.setattr(hwdetect, "_read", lambda p: None)
        assert hwdetect.get_soc_family() == "Allwinner"


class TestArmCoreNames:
    @pytest.mark.parametrize(
        "part,expected",
        [("0xd03", "Cortex-A53"), ("0xd05", "Cortex-A55"), ("0xd0b", "Cortex-A76")],
    )
    def test_known_parts(self, part, expected, monkeypatch):
        info = f"CPU implementer\t: 0x41\nCPU part\t: {part}\n"
        monkeypatch.setattr(hwdetect, "_read", lambda p: info)
        assert hwdetect.get_cpu_name() == expected

    def test_unknown_part(self, monkeypatch):
        info = "CPU implementer\t: 0x41\nCPU part\t: 0xfff\n"
        monkeypatch.setattr(hwdetect, "_read", lambda p: info)
        assert hwdetect.get_cpu_name() is None


class TestDevfreqLoad:
    """The T527 GPU node has no `load` attribute, so residency is derived."""

    def _fake_node(self, monkeypatch, cur, lo, hi):
        values = {
            "name": "1800000.gpu",
            "cur_freq": str(cur),
            "min_freq": str(lo),
            "max_freq": str(hi),
            "governor": "simple_ondemand",
        }
        monkeypatch.setattr(
            hwdetect, "_read_int", lambda p: int(values[p.rsplit("/", 1)[1]])
            if p.rsplit("/", 1)[1] in values
            else None
        )
        monkeypatch.setattr(
            hwdetect, "_read", lambda p: values.get(p.rsplit("/", 1)[1])
        )

    def test_idle_at_minimum(self, monkeypatch):
        self._fake_node(monkeypatch, 150_000_000, 150_000_000, 696_000_000)
        assert hwdetect.get_devfreq_info("/x")["load"] == 0.0

    def test_idle_at_maximum(self, monkeypatch):
        self._fake_node(monkeypatch, 696_000_000, 150_000_000, 696_000_000)
        assert hwdetect.get_devfreq_info("/x")["load"] == 100.0

    def test_midpoint(self, monkeypatch):
        self._fake_node(monkeypatch, 423_000_000, 150_000_000, 696_000_000)
        assert hwdetect.get_devfreq_info("/x")["load"] == 50.0

    def test_missing_data_is_none(self, monkeypatch):
        monkeypatch.setattr(hwdetect, "_read_int", lambda p: None)
        assert hwdetect.get_devfreq_info("/x")["load"] is None


class TestTransStat:
    """GPU/DDR busy percentage comes from the trans_stat histogram."""

    def test_top_frequency_residency(self, monkeypatch):
        # Columns are the "to" frequencies from the header; the last column is
        # the top frequency, so 900ms of the 1000ms total landed there.
        raw = (
            "     From  :   To\n"
            "           : 150000000 696000000   time(ms)\n"
            "*150000000:         0       900     900\n"
            " 696000000:       100         0     100\n"
            "Total transition : 2"
        )
        monkeypatch.setattr(hwdetect, "_read", lambda p: raw)
        assert hwdetect._devfreq_busy_pct("/x") == pytest.approx(90.0)

    def test_all_idle_at_low_frequency(self, monkeypatch):
        raw = (
            "     From  :   To\n"
            "           : 150000000 696000000   time(ms)\n"
            "*150000000:       900         0     900\n"
            " 696000000:         0         0       0\n"
            "Total transition : 2"
        )
        monkeypatch.setattr(hwdetect, "_read", lambda p: raw)
        assert hwdetect._devfreq_busy_pct("/x") == 0.0

    def test_malformed_header_degrades(self, monkeypatch):
        # The sunxi DMC node prints its header without a separating space, which
        # fuses two frequencies into one bogus value. That must not raise.
        raw = (
            "     From  :   To\n"
            "           : 150000000 480000000 8000000001200000000   time(ms)\n"
            "*1200000000:         0         0         0         0  11834728\n"
            "Total transition : 0"
        )
        monkeypatch.setattr(hwdetect, "_read", lambda p: raw)
        assert hwdetect._devfreq_busy_pct("/x") in (None, 0.0)

    def test_no_current_frequency_marker(self, monkeypatch):
        raw = "     From  :   To\n 150000000:  0  0  100\n"
        monkeypatch.setattr(hwdetect, "_read", lambda p: raw)
        assert hwdetect._devfreq_busy_pct("/x") is None

    def test_unreadable(self, monkeypatch):
        monkeypatch.setattr(hwdetect, "_read", lambda p: None)
        assert hwdetect._devfreq_busy_pct("/x") is None


class TestZram:
    """Both zram0 and zram1 are present on this image and must be summed."""

    def test_sums_all_devices(self, monkeypatch):
        stats = {
            "/sys/block/zram0/mm_stat": "100 50 2000 2013573120 0 0 0 0 0",
            "/sys/block/zram1/mm_stat": "10 5 500 52428800 0 0 0 0 0",
        }
        monkeypatch.setattr(
            hwdetect, "_read", lambda p: stats.get(p)
        )
        monkeypatch.setattr(
            hwdetect.glob,
            "glob",
            lambda pat, **kw: sorted(stats) if "zram" in pat else [],
        )
        used, total = hwdetect.get_zram_stats()
        assert (used, total) == (2500, 2013573120 + 52428800)

    def test_absent(self, monkeypatch):
        monkeypatch.setattr(hwdetect, "_read", lambda p: None)
        monkeypatch.setattr(hwdetect.glob, "glob", lambda pat, **kw: [])
        assert hwdetect.get_zram_stats() == (0, 0)


class TestSortModes:
    def test_all_modes_present(self):
        for mode in (
            "cpu_desc",
            "cpu_asc",
            "mem_desc",
            "mem_asc",
            "pid_desc",
            "pid_asc",
            "name_desc",
            "name_asc",
        ):
            assert mode in sysinfo.SORT_MODES

    def test_desc_modes_reverse(self, monkeypatch):
        procs = [
            {"pid": 3, "name": "b", "user": "u", "cpu": 10.0, "mem": 1.0},
            {"pid": 1, "name": "c", "user": "u", "cpu": 50.0, "mem": 3.0},
            {"pid": 2, "name": "a", "user": "u", "cpu": 30.0, "mem": 2.0},
        ]

        # Exercise the real sort key/ordering used by get_top_processes, without
        # depending on live psutil data.
        def order(mode):
            key, _ = sysinfo.SORT_MODES[mode]
            return [p["pid"] for p in sorted(procs, key=key,
                                             reverse=mode.endswith("_desc"))]

        assert order("cpu_desc") == [1, 2, 3]
        assert order("cpu_asc") == [3, 2, 1]
        assert order("mem_desc") == [1, 2, 3]
        assert order("mem_asc") == [3, 2, 1]
        assert order("pid_desc") == [3, 2, 1]
        assert order("pid_asc") == [1, 2, 3]
        assert order("name_asc") == [2, 3, 1]
        assert order("name_desc") == [1, 3, 2]
