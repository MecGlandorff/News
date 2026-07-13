"""Temporary compatibility bridge to :mod:`src.tracker.replay`."""

from src.tracker import replay as _replay


def __getattr__(name):
    return getattr(_replay, name)
