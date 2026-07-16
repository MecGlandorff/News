"""Temporary compatibility bridge to :mod:`src.briefing.selection`."""

from src.briefing import selection as _selection


def __getattr__(name):
    return getattr(_selection, name)
