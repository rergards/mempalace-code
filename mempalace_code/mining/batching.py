"""mining.batching — Hardware batch-size detection and cached state."""

import os
from typing import Optional


def _detect_batch_size() -> int:
    """Return an appropriate batch size based on the available compute device.

    | Device            | Batch | Reason                                      |
    |-------------------|-------|---------------------------------------------|
    | CPU (>4 GB RAM)   |   128 | Proven default on MacBook                   |
    | CPU (<=4 GB RAM)  |    64 | Conservative for low-RAM devices            |

    Falls back to 128 on any detection failure.
    """
    # The default embedding runtime is CPU-only ONNX. Keep sizing independent
    # from optional custom-model dependencies such as Torch.
    try:
        mem_bytes = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        return 128 if mem_bytes / (1024**3) > 4 else 64
    except (AttributeError, ValueError, OSError):
        return 128


_batch_size: Optional[int] = None


def get_batch_size() -> int:
    """Return the appropriate batch size, detecting hardware on first call only."""
    global _batch_size
    if _batch_size is None:
        _batch_size = _detect_batch_size()
    return _batch_size
