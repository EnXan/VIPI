"""Overall percentage of a running `vipi scan`, shown in the status line.

The scanner reports when each file starts; how far a file is cannot be read
from the scanner, because OCR also selects and assesses text without reporting
steps. So the current file moves by time: against the average duration of the
files already finished in this run, or ``FIRST_FILE_SECONDS`` for the first
one. It eases towards the end of the file and never shows it complete before
the next file starts, so the percentage never moves back.
"""

import math
import time

FIRST_FILE_SECONDS = 15.0  # typical local scan of one screenshot; an estimate
EASE = 1.6  # at the expected duration a file shows 80 % (1 - e^-1.6)
FILE_CAP = 0.97  # a running file never shows as complete


class ScanPercent:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.index = 0  # files started
        self.total = 0
        self.started = None
        self.durations = []
        self.shown = 0.0

    def start_file(self, index, total):
        """Record that file `index` (1-based) of `total` starts now."""
        now = self.clock()
        if self.started is not None and index > self.index:
            self.durations.append(now - self.started)
        self.index, self.total, self.started = index, total, now

    def percent(self):
        """Whole percent of the run, or None before the first file starts."""
        if not self.total or self.started is None:
            return None
        expected = (
            sum(self.durations) / len(self.durations)
            if self.durations
            else FIRST_FILE_SECONDS
        )
        elapsed = self.clock() - self.started
        current = min(FILE_CAP, 1 - math.exp(-EASE * elapsed / expected))
        self.shown = max(self.shown, (self.index - 1 + current) / self.total)
        return math.floor(self.shown * 100)
