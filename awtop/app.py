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

"""Interactive main loop: layout, live refresh and key handling."""

import os
import queue
import signal
import sys
import termios
import threading
import time
import tty
from typing import Any

from rich.console import Group
from rich.layout import Layout
from rich.live import Live

from . import panels
from . import sysinfo

#: Hardware probed once at startup; the set of panels never changes afterwards.
CACHE: dict[str, Any] = {}

SORT_MODE = "cpu_desc"
SHOULD_EXIT = False

#: Keys that toggle each sort dimension.
_SORT_KEYS = {
    "c": ("cpu_desc", "cpu_asc"),
    "m": ("mem_desc", "mem_asc"),
    "p": ("pid_desc", "pid_asc"),
    "n": ("name_desc", "name_asc"),
}


def _signal_handler(signum, frame):
    global SHOULD_EXIT
    SHOULD_EXIT = True


def _read_keys(q):
    """Blocking key reader translating escape sequences into logical keys."""
    old = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    try:
        while True:
            b = os.read(sys.stdin.fileno(), 3).decode()
            k = ord(b[2]) if len(b) == 3 else ord(b)
            keymap = {
                127: "backspace",
                10: "return",
                32: "space",
                9: "tab",
                27: "esc",
                65: "up",
                66: "down",
                67: "right",
                68: "left",
            }
            q.put(keymap.get(k, chr(k)))
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


def initialize_cache():
    """Probe the hardware once so missing blocks do not shift the layout."""
    from . import hwdetect

    CACHE["has_gpu"] = hwdetect.get_gpu_path() is not None
    CACHE["has_npu"] = hwdetect.has_npu()
    CACHE["has_dmc"] = hwdetect.get_dmc_path() is not None
    CACHE["sys_panel"] = panels.build_sys_panel()


def build_layout():
    """Two-column top (peripherals right, CPU/mem left) over I/O and processes."""
    left_panels = [panels.build_cpu_panel(), panels.build_mem_panel()]

    right_panels = [CACHE["sys_panel"]]
    if CACHE["has_gpu"]:
        right_panels.append(panels.build_gpu_panel())
    if CACHE["has_npu"]:
        right_panels.append(panels.build_npu_panel())
    if CACHE["has_dmc"]:
        right_panels.append(panels.build_dmc_panel())

    top_layout = Layout(name="top", size=24, minimum_size=24)
    top_layout.split_row(
        Layout(Group(*left_panels), name="left"),
        Layout(Group(*right_panels), name="right"),
    )

    bottom_layout = Layout(name="bottom")
    bottom_layout.split_row(
        Layout(
            Group(panels.build_io_table(), panels.build_thermal_table()),
            name="left",
            ratio=6,
        ),
        Layout(panels.build_process_panel(SORT_MODE), name="right", ratio=15),
    )

    root_layout = Layout()
    root_layout.split(top_layout, bottom_layout)
    return root_layout


def _handle_key(key):
    """Apply a keypress to the sort mode; return False to quit."""
    global SORT_MODE

    if key in ("q", "Q", "esc"):
        return False
    for letter, (desc, asc) in _SORT_KEYS.items():
        if key in (letter, letter.upper()):
            SORT_MODE = asc if SORT_MODE == desc else desc
            return True
    return True


def main():
    initialize_cache()
    signal.signal(signal.SIGINT, _signal_handler)

    q = queue.Queue()
    threading.Thread(target=_read_keys, args=(q,), daemon=True).start()

    old = termios.tcgetattr(sys.stdin)
    try:
        with Live(build_layout(), refresh_per_second=0.75, screen=True) as live:
            while not SHOULD_EXIT:
                time.sleep(1.5)
                if not q.empty():
                    if not _handle_key(q.get()):
                        break
                live.update(build_layout())
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
        os.system("stty sane")


__all__ = ["main", "build_layout", "initialize_cache", "sysinfo"]
