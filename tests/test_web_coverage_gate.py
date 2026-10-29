import pytest

from scripts import check_web_coverage


def create_report(tmp_path, monkeypatch, missing_line=0, missing_branch=0):
    source = tmp_path / 'static'
    source.mkdir()
    script = source / 'app.js'
    script.write_text('// source')
    monkeypatch.setattr(check_web_coverage, 'SOURCE_DIR', source)
    report = tmp_path / 'lcov.info'
    lines = ['SF:' + script.as_posix()]
    lines += ['DA:{},{}'.format(n, int(n != missing_line)) for n in range(1, 21)]
    lines += ['BRDA:{},0,0,{}'.format(n, int(n != missing_branch)) for n in range(1, 21)]
    lines += ['end_of_record']
    report.write_text('\n'.join(lines))
    return report, script.as_posix()


def test_web_gate_checks_overall_and_changed_lines_and_branches(tmp_path, monkeypatch):
    report, name = create_report(tmp_path, monkeypatch, missing_line=20, missing_branch=19)
    assert check_web_coverage.main(str(report)) == 0
    monkeypatch.setattr(check_web_coverage, 'changed_lines', lambda base: {name: {1}})
    assert check_web_coverage.main(str(report), 'base') == 0
    monkeypatch.setattr(check_web_coverage, 'changed_lines', lambda base: {name: {20}})
    assert check_web_coverage.main(str(report), 'base') == 1
    monkeypatch.setattr(check_web_coverage, 'changed_lines', lambda base: {name: {19}})
    assert check_web_coverage.main(str(report), 'base') == 1


def test_web_gate_rejects_missing_sources_and_branch_data(tmp_path, monkeypatch):
    report, name = create_report(tmp_path, monkeypatch)
    (tmp_path / 'static' / 'missing.js').write_text('')
    with pytest.raises(ValueError, match='missing from coverage'):
        check_web_coverage.main(str(report))
    (tmp_path / 'static' / 'missing.js').unlink()
    report.write_text('SF:{}\nDA:1,1\nend_of_record\n'.format(name))
    with pytest.raises(ValueError, match='lacks branches'):
        check_web_coverage.main(str(report))
