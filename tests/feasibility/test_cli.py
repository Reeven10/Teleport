"""Tests for dev.feasibility.cli runner (P3)."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from dev.feasibility.cli import main
from tests.feasibility.fixtures import (
    ALL_DEVICE_FILES,
    ALL_LINK_FILES,
    ALL_MANIFEST_FILES,
)


class TestCliRunner:
    def test_cli_basic_run(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(
                [
                    "--manifest",
                    "manifest_light_python.json",
                    "--source",
                    "device_source_default.json",
                    "--target",
                    "device_windows_laptop.json",
                    "--link",
                    "link_cable.json",
                ]
            )
        assert ret == 0
        output = buf.getvalue()
        assert "TELEPORT FEASIBILITY EVALUATION" in output
        assert "Architecture" in output
        assert "RAM (Free)" in output
        assert "Summary:" in output
        assert "[MIGRATE]" in output

    def test_cli_remote_access_verdict(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(
                [
                    "--manifest",
                    "manifest_remote_only_gui.json",
                    "--source",
                    "device_source_default.json",
                    "--target",
                    "device_macos_laptop.json",
                    "--link",
                    "link_good_wifi.json",
                ]
            )
        assert ret == 0
        output = buf.getvalue()
        assert "[REMOTE_ACCESS]" in output

    def test_cli_stay_verdict(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(
                [
                    "--manifest",
                    "manifest_heavy_ml.json",
                    "--source",
                    "device_source_default.json",
                    "--target",
                    "device_low_spec_arm.json",
                    "--link",
                    "link_lossy.json",
                ]
            )
        assert ret == 0
        output = buf.getvalue()
        assert "[STAY]" in output

    def test_cli_no_link(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(
                [
                    "--manifest",
                    "manifest_light_python.json",
                    "--source",
                    "device_source_default.json",
                    "--target",
                    "device_windows_laptop.json",
                    "--link",
                    "none",
                ]
            )
        assert ret == 0
        output = buf.getvalue()
        assert "link.no_link" in output

    @pytest.mark.parametrize("manifest_file", ALL_MANIFEST_FILES)
    @pytest.mark.parametrize("device_file", ALL_DEVICE_FILES)
    def test_cli_all_fixtures_smoke(self, manifest_file: str, device_file: str) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(
                [
                    "--manifest",
                    manifest_file,
                    "--source",
                    "device_source_default.json",
                    "--target",
                    device_file,
                    "--link",
                    "link_good_wifi.json",
                ]
            )
        assert ret == 0
        output = buf.getvalue()
        assert "Summary:" in output
        assert "Verdict:" in output

