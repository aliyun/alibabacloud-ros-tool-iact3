"""Enforce line and branch thresholds on instrumented browser JavaScript."""
import sys
from pathlib import Path

try:
    from .check_coverage import changed_lines, check
except ImportError:
    from check_coverage import changed_lines, check

SOURCE_DIR = Path('iact3/web/static')


def read_lcov(path):
    files = {}
    current = None
    with open(path, encoding='utf-8') as report:
        for line in report:
            line = line.strip()
            if line.startswith('SF:'):
                name = Path(line[3:]).as_posix()
                if name in files:
                    raise ValueError('Duplicate coverage record: {}'.format(name))
                current = files[name] = {'lines': {}, 'branches': []}
            elif line.startswith('DA:') and current is not None:
                number, hits = line[3:].split(',')[:2]
                current['lines'][int(number)] = int(hits)
            elif line.startswith('BRDA:') and current is not None:
                number, _, _, hits = line[5:].split(',')
                current['branches'].append((int(number), 0 if hits == '-' else int(hits)))
            elif line == 'end_of_record':
                current = None
    return files


def main(report_path, base=None):
    files = read_lcov(report_path)
    sources = {path.as_posix() for path in SOURCE_DIR.rglob('*.js')}
    missing = sources - set(files)
    if missing:
        raise ValueError('JavaScript missing from coverage report: {}'.format(', '.join(sorted(missing))))
    line_total = line_covered = branch_total = branch_covered = 0
    changed_line_total = changed_line_covered = changed_branch_total = changed_branch_covered = 0
    changes = changed_lines(base) if base else {}
    for name in sources:
        file = files[name]
        lines = file['lines']
        branches = file['branches']
        line_total += len(lines)
        line_covered += sum(hits > 0 for hits in lines.values())
        branch_total += len(branches)
        branch_covered += sum(hits > 0 for _, hits in branches)
        changed = changes.get(name, set())
        changed_line_total += sum(number in changed for number in lines)
        changed_line_covered += sum(number in changed and hits > 0 for number, hits in lines.items())
        changed_branch_total += sum(number in changed for number, _ in branches)
        changed_branch_covered += sum(number in changed and hits > 0 for number, hits in branches)
    if not line_total or not branch_total:
        raise ValueError('JavaScript coverage report is empty or lacks branches')
    passed = check('Web overall lines', line_covered, line_total)
    passed &= check('Web overall branches', branch_covered, branch_total)
    if base:
        passed &= check('Web changed lines', changed_line_covered, changed_line_total)
        passed &= check('Web changed branches', changed_branch_covered, changed_branch_total)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
