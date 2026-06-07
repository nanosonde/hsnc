"""Tests for backend log-level resolution from HSNC_LOG_LEVEL."""

from __future__ import annotations

import logging

import pytest

from hsnc.logging_config import configure_logging, resolve_level


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("debug", logging.DEBUG),
        ("DEBUG", logging.DEBUG),
        ("Info", logging.INFO),
        ("info", logging.INFO),
        ("warn", logging.WARNING),
        ("warning", logging.WARNING),
        ("WARNING", logging.WARNING),
        ("error", logging.ERROR),
        ("critical", logging.CRITICAL),
        ("  debug  ", logging.DEBUG),
    ],
)
def test_resolve_level_known(name, expected):
    assert resolve_level(name) == expected


@pytest.mark.parametrize("name", ["", None, "verbose", "trace", "nonsense"])
def test_resolve_level_unknown_falls_back_to_info(name):
    assert resolve_level(name) == logging.INFO


def test_configure_logging_sets_package_logger_not_root(monkeypatch):
    monkeypatch.setenv("HSNC_LOG_LEVEL", "debug")
    resolved = configure_logging()
    assert resolved == logging.DEBUG
    assert logging.getLogger("hsnc").level == logging.DEBUG
    # Root must stay quiet so third-party libraries are not unleashed.
    assert logging.getLogger().level != logging.DEBUG


def test_configure_logging_explicit_string_overrides_env(monkeypatch):
    monkeypatch.setenv("HSNC_LOG_LEVEL", "debug")
    assert configure_logging("error") == logging.ERROR
    assert logging.getLogger("hsnc").level == logging.ERROR
