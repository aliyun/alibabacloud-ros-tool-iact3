from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_root_makefile_exposes_standard_dev_targets():
    makefile = ROOT / "Makefile"

    content = makefile.read_text()

    for target in ("install", "build", "format", "lint", "run", "test"):
        assert f"{target}:" in content

    assert "uv venv" in content
    assert 'uv pip install -e ".[dev,binary]"' in content
    assert "ruff check" in content
    assert "ruff format" in content
    assert "ty check" in content
    assert "uv run --extra binary python build.py" in content
    assert "uv run iact3" in content
    assert "pytest" in content


def test_pyproject_declares_project_metadata_and_dev_tools():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["name"] == "alibabacloud-ros-iact3"
    assert pyproject["project"]["scripts"]["iact3"] == "iact3.__main__:sync_run"
    assert "dependencies" in pyproject["project"]

    optional_dependencies = pyproject["project"]["optional-dependencies"]
    assert optional_dependencies["binary"] == ["pyinstaller==6.11.1"]
    assert "ruff" in optional_dependencies["dev"]
    assert "ty" in optional_dependencies["dev"]
