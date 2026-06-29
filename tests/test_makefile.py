from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]

REQUIREMENTS_REFERENCING_PATHS = [
    ROOT / "Dockerfile",
    ROOT / "MANIFEST.in",
    ROOT / "README.md",
    ROOT / "tox.ini",
    ROOT / "website" / "docs" / "developer.md",
    ROOT / "website" / "docs" / "installation.md",
    ROOT / "website" / "i18n" / "zh-cn" / "docusaurus-plugin-content-docs" / "current" / "developer.md",
    ROOT / "website" / "i18n" / "zh-cn" / "docusaurus-plugin-content-docs" / "current" / "installation.md",
]


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
    project = pyproject["project"]

    assert project["name"] == "alibabacloud-ros-iact3"
    assert project["scripts"]["iact3"] == "iact3.__main__:sync_run"
    assert project["requires-python"] == ">=3.7,<3.15"
    assert project["license"] == {"text": "Apache-2.0"}
    assert "dependencies" in project

    classifiers = project["classifiers"]
    for python_version in ("3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "3.13", "3.14"):
        assert f"Programming Language :: Python :: {python_version}" in classifiers

    optional_dependencies = project["optional-dependencies"]
    assert optional_dependencies["binary"] == ["pyinstaller==6.21.0; python_version >= '3.8'"]
    assert "ruff" in optional_dependencies["dev"]
    assert "ty; python_version >= '3.8'" in optional_dependencies["dev"]


def test_project_uses_pyproject_instead_of_requirements_files():
    assert not (ROOT / "requirements.txt").exists()
    assert not (ROOT / "requirements-dev.txt").exists()

    for path in REQUIREMENTS_REFERENCING_PATHS:
        content = path.read_text()
        assert "requirements.txt" not in content
        assert "requirements-dev.txt" not in content
