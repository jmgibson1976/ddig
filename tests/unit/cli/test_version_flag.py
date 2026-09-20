import re
from typer.testing import CliRunner
from ddig.__main__ import app

runner = CliRunner()


def test_version_flag_exits_zero() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0


def test_version_flag_outputs_semver() -> None:
    result = runner.invoke(app, ["--version"])
    assert re.search(r"\d+\.\d+\.\d+", result.output), (
        f"Expected semver in output, got: {result.output!r}"
    )