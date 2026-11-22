import importlib.util
import logging
import subprocess
import sys

import pytest

from vipi.torch_logging import REDIRECTS_LOGGER, quiet_redirects_notice

# Imports torch's redirects module as on macOS, in a fresh interpreter because
# the notice is emitted only once, at module import. torch's loggers do not
# propagate to root, so the handler sits on the redirects logger. No model loads.
IMPORT_AS_DARWIN = """
import logging, sys
records = []
handler = logging.Handler()
handler.emit = records.append
import torch
logging.getLogger({logger!r}).addHandler(handler)
if {quiet}:
    from vipi.torch_logging import quiet_redirects_notice
    quiet_redirects_notice()
platform, sys.platform = sys.platform, "darwin"
try:
    import torch.distributed.elastic.multiprocessing.redirects
finally:
    sys.platform = platform
print(sum("Redirects are currently not supported" in r.getMessage() for r in records))
"""


def test_quiet_redirects_notice_raises_only_that_logger():
    logger = logging.getLogger(REDIRECTS_LOGGER)
    parent = logging.getLogger("torch.distributed.elastic.multiprocessing")
    previous = logger.level, parent.level
    try:
        logger.setLevel(logging.NOTSET)
        quiet_redirects_notice()
        assert logger.level == logging.ERROR
        assert parent.level == previous[1]
    finally:
        logger.setLevel(previous[0])


@pytest.mark.skipif(
    importlib.util.find_spec("torch") is None, reason="needs detector-local torch"
)
@pytest.mark.parametrize(("quiet", "expected"), [(False, "1"), (True, "0")])
def test_macos_redirects_notice_is_emitted_only_without_helper(quiet, expected):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            IMPORT_AS_DARWIN.format(quiet=quiet, logger=REDIRECTS_LOGGER),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == expected
