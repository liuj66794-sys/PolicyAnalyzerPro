from __future__ import annotations

import os

from core.config import AppConfig, DEFAULT_CONFIG


def initialize_runtime_environment(config: AppConfig | None = None) -> None:
    """
    Enforce fully offline transformer loading and keep CPU usage predictable.
    This helper is safe to call from both the main process and worker processes.
    """
    cfg = config or DEFAULT_CONFIG

    for key, value in cfg.offline_env.items():
        os.environ[key] = str(value)

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    try:
        import torch
    except ImportError:
        return

    try:
        torch.set_num_threads(cfg.torch_num_threads)
    except Exception:
        pass

    if hasattr(torch, "set_num_interop_threads"):
        try:
            torch.set_num_interop_threads(1)
        except Exception:
            pass
