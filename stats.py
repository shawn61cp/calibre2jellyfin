#!/usr/bin/python3

import sys
import pstats
from pstats import SortKey

p = pstats.Stats(sys.argv[1])
if len(sys.argv) > 2:
    p.add(*sys.argv[2:])
p.sort_stats(SortKey.CUMULATIVE).print_stats(30)
