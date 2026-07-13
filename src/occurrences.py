"""Temporary compatibility bridge to :mod:`src.tracker.occurrences`."""

from src.tracker import occurrences as _occurrences


def __getattr__(name):
    return getattr(_occurrences, name)
