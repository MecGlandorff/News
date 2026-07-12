"""Temporary compatibility bridge to :mod:`src.tracker.matching`."""

from src.tracker import matching as _matching


__all__ = _matching.__all__


def __getattr__(name):
    return getattr(_matching, name)
