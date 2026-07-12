"""Temporary compatibility bridge to :mod:`src.briefing`."""

from src import briefing as _briefing


def __getattr__(name):
    return getattr(_briefing, name)
