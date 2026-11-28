from vipi.scan_progress import FIRST_FILE_SECONDS, ScanPercent


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_percentage_moves_by_time_and_learns_from_finished_files():
    clock = Clock()
    tracker = ScanPercent(clock)
    assert tracker.percent() is None  # nothing started yet

    tracker.start_file(1, 2)
    assert tracker.percent() == 0
    clock.now = FIRST_FILE_SECONDS
    assert tracker.percent() == 39  # 80 % of the first of two files
    clock.now = 10 * FIRST_FILE_SECONDS
    assert tracker.percent() == 48  # never complete before the next file starts

    tracker.start_file(2, 2)  # the first file took 10 * FIRST_FILE_SECONDS
    assert tracker.percent() == 50
    clock.now += 10 * FIRST_FILE_SECONDS
    assert tracker.percent() == 89


def test_percentage_never_moves_back():
    clock = Clock()
    tracker = ScanPercent(clock)
    tracker.start_file(1, 1)
    clock.now = 100.0
    high = tracker.percent()
    tracker.start_file(1, 1)  # a repeated report of the same file
    assert tracker.percent() >= high
