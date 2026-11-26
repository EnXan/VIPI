"""Load local transformers weights sequentially (ADR 0086)."""

import os

# transformers reads this switch on every from_pretrained() call. Its threaded
# loading can deadlock in safetensors: one thread initializes a lazy tensor slice
# and waits for the GIL while another holds the GIL and waits for that slice.
ASYNC_LOAD_SWITCH = "HF_DEACTIVATE_ASYNC_LOAD"


def load_weights_sequentially():
    """Turn off threaded weight loading unless the environment already sets it."""
    os.environ.setdefault(ASYNC_LOAD_SWITCH, "1")
