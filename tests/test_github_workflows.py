from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_workflow(path):
    workflow = yaml.safe_load(path.read_text())

    # PyYAML still treats the GitHub Actions "on" key as a boolean unless a
    # YAML 1.2 loader is used.
    if True in workflow and "on" not in workflow:
        workflow["on"] = workflow.pop(True)

    return workflow


def test_unit_tests_workflow_runs_full_python_test_suite():
    workflow_path = ROOT / ".github" / "workflows" / "unit-tests.yml"

    assert workflow_path.exists()

    workflow = _load_workflow(workflow_path)
    triggers = workflow["on"]
    job = workflow["jobs"]["test"]

    assert triggers["pull_request"] == {}
    assert triggers["push"]["branches"] == ["master"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.7", "3.14"]

    steps = job["steps"]
    uses_steps = [step["uses"] for step in steps if "uses" in step]
    run_steps = [step["run"] for step in steps if "run" in step]

    assert "actions/checkout@v4" in uses_steps
    assert "actions/setup-python@v5" in uses_steps
    assert "astral-sh/setup-uv@v5" in uses_steps
    assert "uv sync --extra dev" in run_steps
    assert "uv run pytest tests" in run_steps


def test_build_binary_workflow_installs_from_project_metadata():
    workflow_path = ROOT / ".github" / "workflows" / "build-binary.yml"

    assert workflow_path.exists()

    workflow = _load_workflow(workflow_path)
    steps = workflow["jobs"]["build"]["steps"]
    setup_python = next(step for step in steps if step.get("uses") == "actions/setup-python@v5")
    run_steps = [step["run"] for step in steps if "run" in step]

    assert setup_python["with"]["cache-dependency-path"] == "pyproject.toml"
    assert any('pip install ".[binary]"' in step for step in run_steps)

    workflow_content = workflow_path.read_text()
    assert "requirements.txt" not in workflow_content
    assert "requirements-dev.txt" not in workflow_content
