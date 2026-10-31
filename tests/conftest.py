"""Shared fixtures. Each test gets a fresh TELEPORT_HOME in tmp_path."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teleport.core import Context, Settings, build_context, create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(home=tmp_path / "home", port=8765, uiDist=tmp_path / "no-ui")


@pytest.fixture
def ctx(settings: Settings) -> Context:
    return build_context(settings)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c
