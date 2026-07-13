"""Temporary compatibility bridge to :mod:`src.tracker.store`."""

from src.tracker import store as _store


def __getattr__(name):
    return getattr(_store, name)
