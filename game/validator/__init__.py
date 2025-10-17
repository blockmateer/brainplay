from __future__ import annotations

from typing import Any

__all__ = ("forward", "get_rewards")


def forward(*args: Any, **kwargs: Any):
    from .forward import forward as _forward

    return _forward(*args, **kwargs)


def get_rewards(*args: Any, **kwargs: Any):
    from .reward import get_rewards as _get_rewards

    return _get_rewards(*args, **kwargs)
