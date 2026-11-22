"""Quiet torch import notices that carry no information for VIPI users."""

import logging

# torch logs "Redirects are currently not supported in Windows or MacOs." once
# when this module is imported on macOS/Windows (transformers' modeling code
# pulls it in). VIPI never uses torch elastic redirects.
REDIRECTS_LOGGER = "torch.distributed.elastic.multiprocessing.redirects"


def quiet_redirects_notice():
    """Raise only the redirects logger to ERROR; call before importing torch."""
    logging.getLogger(REDIRECTS_LOGGER).setLevel(logging.ERROR)
