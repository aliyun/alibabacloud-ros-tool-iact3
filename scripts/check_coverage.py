"""Check overall and changed-line coverage from coverage.py's JSON report."""
import json
import re
import subprocess
import sys
from pathlib import Path

THRESHOLD = 95
HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')


def changed_lines(base):
    names = subprocess.check_output(['git', 'diff', '--name-only', '-z', '--diff-filter=ACMR', base, 'HEAD'])
    changes = {}
    for name in names.decode('utf-8').split('\0'):
        if not name.endswith(('.py', '.js')):
            continue
        diff = subprocess.check_output(
            ['git', 'diff', '--no-ext-diff', '--unified=0', base, 'HEAD', '--', name], text=True
        )
        lines = set()
        for line in diff.splitlines():
            match = HUNK.match(line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) is not None else 1
                lines.update(range(start, start + count))
        changes[name] = lines
    return changes


def check(label, covered, total):
    percent = 100 * covered / total if total else 100.0
    print('{}: {}/{} ({:.2f}%), minimum {}%'.format(label, covered, total, percent, THRESHOLD))
    return covered * 100 >= total * THRESHOLD


def source_files():
    return {path.as_posix() for path in Path('iact3').rglob('*.py')}


def main(report_path, base=None):
    with open(report_path, encoding='utf-8') as report_file:
        report = json.load(report_file)
    if not report['meta']['branch_coverage']:
        raise ValueError('Branch coverage is required')
    missing_sources = source_files() - set(report['files'])
    if missing_sources:
        raise ValueError('Python missing from coverage report: {}'.format(', '.join(sorted(missing_sources))))
    totals = report['totals']
    if not totals['num_statements'] or not totals['num_branches']:
        raise ValueError('Python coverage report is empty or lacks branches')
    passed = check('Overall lines', totals['covered_lines'], totals['num_statements'])
    passed &= check('Overall branches', totals['covered_branches'], totals['num_branches'])
    if base:
        changes = changed_lines(base)
        line_covered = line_total = branch_covered = branch_total = 0
        for name, lines in changes.items():
            if not name.startswith('iact3/') or not name.endswith('.py'):
                continue
            if name not in report['files']:
                raise ValueError('Changed source file absent from coverage report: {}'.format(name))
            file = report['files'][name]
            executed = set(file['executed_lines']) & lines
            missing = set(file['missing_lines']) & lines
            line_covered += len(executed)
            line_total += len(executed) + len(missing)
            covered_arcs = [arc for arc in file['executed_branches'] if arc[0] in lines]
            missing_arcs = [arc for arc in file['missing_branches'] if arc[0] in lines]
            branch_covered += len(covered_arcs)
            branch_total += len(covered_arcs) + len(missing_arcs)
        passed &= check('Changed lines', line_covered, line_total)
        passed &= check('Changed branches', branch_covered, branch_total)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
