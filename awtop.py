#!/usr/bin/env python3
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

"""Command-line entry point for awtop."""

import os
import sys

# Allow running straight from a checkout without installing.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from awtop.app import main  # noqa: E402

if __name__ == "__main__":
    # The NPU and GPU stats live in debugfs, which is root-only. Refusing early
    # is friendlier than rendering a wall of empty panels.
    if os.geteuid() != 0:
        print("Root permissions required. Use: sudo awtop")
        sys.exit(1)
    main()
