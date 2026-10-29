import json

import pytest

from scripts import check_coverage


@pytest.fixture(autouse=True)
def known_sources(monkeypatch):
    monkeypatch.setattr(check_coverage, 'source_files', lambda: {'iact3/example.py'})


def write_report(tmp_path, covered_lines=19, covered_branches=19):
    report = {
        'meta': {'branch_coverage': True},
        'totals': {'covered_lines': covered_lines, 'num_statements': 20,
                   'covered_branches': covered_branches, 'num_branches': 20},
        'files': {'iact3/example.py': {
            'executed_lines': list(range(1, 20)), 'missing_lines': [20],
            'executed_branches': [[1, 2], [1, 3]], 'missing_branches': [[2, 3]],
        }},
    }
    path = tmp_path / 'coverage.json'
    path.write_text(json.dumps(report))
    return path


@pytest.mark.parametrize('lines,branches,expected', [(19, 19, 0), (18, 19, 1), (19, 18, 1)])
def test_overall_gates_are_independent(tmp_path, lines, branches, expected):
    assert check_coverage.main(str(write_report(tmp_path, lines, branches))) == expected


def test_changed_lines_and_branches_are_gated(tmp_path, monkeypatch):
    report = str(write_report(tmp_path))
    monkeypatch.setattr(check_coverage, 'changed_lines', lambda base: {'iact3/example.py': {1}})
    assert check_coverage.main(report, 'base') == 0
    monkeypatch.setattr(check_coverage, 'changed_lines', lambda base: {'iact3/example.py': {2}})
    assert check_coverage.main(report, 'base') == 1
    monkeypatch.setattr(check_coverage, 'changed_lines', lambda base: {'iact3/example.py': {20}})
    assert check_coverage.main(report, 'base') == 1
    monkeypatch.setattr(check_coverage, 'changed_lines', lambda base: {'iact3/new.py': {1}})
    with pytest.raises(ValueError, match='absent'):
        check_coverage.main(report, 'base')


def test_hunks_include_new_lines_and_ignore_deletions(monkeypatch):
    def git(command, **kwargs):
        if '--name-only' in command:
            return b'iact3/example.py\0'
        return '@@ -1,2 +1,3 @@\n@@ -8,1 +9,0 @@\n@@ -10 +10 @@\n'

    monkeypatch.setattr(check_coverage.subprocess, 'check_output', git)
    assert check_coverage.changed_lines('base') == {'iact3/example.py': {1, 2, 3, 10}}


def test_changed_lines_from_real_git_diff(tmp_path, monkeypatch):
    import subprocess

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=str(tmp_path), text=True).strip()

    git('init', '-q')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Coverage Test')
    git('config', 'commit.gpgsign', 'false')
    git('config', 'core.hooksPath', str(tmp_path / 'no-hooks'))
    source = tmp_path / 'iact3'
    source.mkdir()
    (source / 'example.py').write_text('one\ntwo\nthree\nfour\n')
    git('add', '.')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    (source / 'example.py').write_text('one\nchanged\nthree\nfour\nadded\n')
    (source / 'new.py').write_text('first\nsecond\n')
    (source / 'app.js').write_text('const value = 1;\n')
    git('add', '.')
    git('commit', '-qm', 'change')
    monkeypatch.chdir(tmp_path)
    assert check_coverage.changed_lines(base) == {
        'iact3/example.py': {2, 5}, 'iact3/new.py': {1, 2}, 'iact3/app.js': {1},
    }


@pytest.mark.parametrize('field', ['num_statements', 'num_branches'])
def test_empty_overall_coverage_is_rejected(tmp_path, field):
    path = write_report(tmp_path)
    report = json.loads(path.read_text())
    report['totals'][field] = 0
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='empty or lacks branches'):
        check_coverage.main(str(path))


def test_missing_source_is_rejected_for_overall_coverage(tmp_path, monkeypatch):
    report = str(write_report(tmp_path))
    monkeypatch.setattr(check_coverage, 'source_files', lambda: {'iact3/example.py', 'iact3/nested/new.py'})
    with pytest.raises(ValueError, match='iact3/nested/new.py'):
        check_coverage.main(report)


def test_source_discovery_includes_nested_non_package(tmp_path, monkeypatch):
    monkeypatch.undo()
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'iact3' / 'nested'
    source.mkdir(parents=True)
    (source / 'example.py').write_text('value = 1')
    assert check_coverage.source_files() == {'iact3/nested/example.py'}
