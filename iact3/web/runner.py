 # -*- coding: utf-8 -*-
import asyncio
import contextlib
import contextvars
import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

from iact3.config import DEFAULT_CONFIG_FILE, DEFAULT_OUTPUT_DIRECTORY, DEFAULT_PROJECT_ROOT
from iact3.testing.ros_stack import StackTest
from iact3.report.generate_reports import ReportBuilder

LOG = logging.getLogger(__name__)


def _ensure_utc_suffix(time_str: str) -> str:
    """Ensure ROS API time strings are interpreted as UTC by the browser.

    The Alibaba Cloud ROS API returns CreateTime/StatusTime in ISO 8601 UTC
    format but WITHOUT the trailing 'Z' suffix (e.g. '2026-07-20T09:26:56').
    Browsers parse such strings as local time, causing an 8-hour display
    offset in UTC+8 timezones.  This helper appends 'Z' when the string
    lacks timezone info so the browser correctly interprets it as UTC.
    """
    if not time_str or not isinstance(time_str, str):
        return time_str or ''
    s = time_str.strip()
    if not s:
        return ''
    # Already has timezone info (Z, +08:00, or +0800)
    if s.endswith('Z') or s.endswith('z'):
        return s
    # Check for ±HH:MM or ±HHMM offset at end
    import re
    if re.search(r'[+-]\d{2}:?\d{2}$', s):
        return s
    # Assume UTC and append Z
    return s + 'Z'


# Context variable to isolate log capture per asyncio task.
# Each capture_iact3_logs session gets a unique ID; the handler filter
# only accepts logs emitted from the same context, preventing
# cross-contamination when multiple operations run concurrently.
_log_capture_ctx: contextvars.ContextVar = contextvars.ContextVar('_log_capture_ctx', default=None)


@contextlib.contextmanager
def capture_iact3_logs(log_path: Path):
    """Temporarily capture all iact3 package logs to a file.

    Uses a context variable so that only logs from the current asyncio
    task (and its children) are captured.  This prevents logs from
    concurrent operations (e.g. validate / cost) from leaking into the
    test-run log file.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    ctx_id = uuid.uuid4().hex
    token = _log_capture_ctx.set(ctx_id)

    logger = logging.getLogger('iact3')
    handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)-7s] : %(message)s'))

    # Filter: only accept logs emitted within this capture context.
    class _CtxFilter(logging.Filter):
        def filter(self, record):
            return _log_capture_ctx.get() == ctx_id

    handler.addFilter(_CtxFilter())
    logger.addHandler(handler)
    original_level = logger.level
    # Force level to INFO so that INFO logs are captured even if the parent
    # logger was initialized with a higher level (e.g. ERROR in main.py).
    logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(original_level)
        _log_capture_ctx.reset(token)

# Directory for persisting test run state across server restarts
_RUNS_DIR = Path(DEFAULT_PROJECT_ROOT) / '.iact3' / 'runs'

# Maximum number of run output directories to keep under iact3_outputs/runs/
_MAX_OUTPUT_RUNS = 50


class TestRun:
    """Represents a single test run with its state and results."""

    def __init__(self, run_id: str, name: str, params: dict):
        self.id = run_id
        self.name = name
        self.params = params
        self.status = 'pending'  # pending, running, completed, failed
        self.progress = 0
        self.created_at = datetime.now().isoformat()
        self.completed_at = None
        self.stacks = []
        self.error = None
        self.report_path = None
        self.log_path = None
        self._test: Optional[StackTest] = None
        self._task: Optional[asyncio.Task] = None
        # Non-secret fingerprint of the credential used for this run
        # (last 4 chars of access_key_id) to prevent cross-account deletion.
        self.credential_key_id = None

    def to_dict(self, include_logs: bool = False):
        # Apply UTC suffix fix to stack times at serialization point so all
        # code paths (active runs, persisted loads, disk reloads) are covered.
        stacks_out = []
        for _s in self.stacks:
            if isinstance(_s, dict):
                _s_copy = dict(_s)
                _s_copy['create_time'] = _ensure_utc_suffix(_s_copy.get('create_time', ''))
                _s_copy['status_time'] = _ensure_utc_suffix(_s_copy.get('status_time', ''))
                stacks_out.append(_s_copy)
            else:
                stacks_out.append(_s)
        data = {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'progress': self.progress,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'stacks': stacks_out,
            'error': self.error,
            'params': self.params,
            'report_path': str(self.report_path) if self.report_path else None,
            'report_url': self._report_url(),
            'log_path': str(self.log_path) if self.log_path else None,
            'credential_key_id': self.credential_key_id,
        }
        if include_logs:
            data['logs'] = self._load_logs()
        return data

    def _load_logs(self):
        """Load per-stack text logs from the run output directory."""
        logs = []
        if not self.report_path or not self.report_path.exists():
            return logs
        try:
            for log_file in sorted(self.report_path.glob('*.txt')):
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        logs.append({'name': log_file.name, 'content': f.read()})
                except Exception as ex:
                    LOG.warning(f'Failed to read log {log_file}: {ex}')
        except Exception as ex:
            LOG.warning(f'Failed to load logs for run {self.id}: {ex}')
        return logs

    def _report_url(self):
        """Return a web-accessible URL for this run's HTML report."""
        if not self.report_path:
            return None
        index_html = Path(self.report_path) / 'index.html'
        if not index_html.exists():
            return None
        try:
            output_root = Path(DEFAULT_PROJECT_ROOT) / DEFAULT_OUTPUT_DIRECTORY
            rel = Path(self.report_path).relative_to(output_root)
            return f'/outputs/{rel.as_posix()}/index.html'
        except ValueError:
            return None

    # ROS stack statuses that mean the stack is still transitioning
    _IN_PROGRESS_STATUSES = frozenset({
        'CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS', 'DELETE_IN_PROGRESS',
        'CREATE_ROLLBACK_IN_PROGRESS', 'ROLLBACK_IN_PROGRESS',
    })

    def update_stacks(self, force: bool = False):
        """Update stack status from the running test.

        Args:
            force: If True, collect stacks data even in terminal states
                   (used for the final snapshot before saving to disk).
        """
        if not self._test or not self._test.stacker:
            return
        # Always collect the latest stacks data
        # Build a map of previously known statuses so we can preserve them
        # if a stack temporarily reports empty status (e.g. right after delete_stack API call).
        prev_status: dict = {s['stack_name']: s['status'] for s in self.stacks if s.get('status')}

        stacks_info = []
        for stack in self._test.stacker.stacks:
            raw_status = stack.status or ''
            # If status is temporarily empty but we had a known status before,
            # keep the previous status to avoid progress bouncing back to 0.
            effective_status = raw_status or prev_status.get(stack.name or '', '')
            stacks_info.append({
                'test_name': stack.test_name,
                'region': stack.region,
                'stack_id': stack.id or '',
                'stack_name': stack.name or '',
                'status': effective_status,
                'status_reason': stack.status_reason or '',
                'launch_succeeded': stack.launch_succeeded,
                'create_time': _ensure_utc_suffix(stack.create_time),
                'status_time': _ensure_utc_suffix(stack.status_time),
            })
        self.stacks = stacks_info

        # Don't recalculate progress for terminal states (unless forced)
        if not force and self.status in ('completed', 'failed', 'cancelled'):
            return

        # Calculate progress considering run options and deletion phase
        total = len(stacks_info)
        if total <= 0:
            return

        p = self.params or {}
        no_delete = p.get('no_delete', False)
        dont_wait = p.get('dont_wait_for_delete', False)
        keep_failed = p.get('keep_failed', False)
        # If no_delete, only create phase; otherwise create + delete phases
        create_weight = 50 if not no_delete else 100

        progress_sum = 0
        for s in stacks_info:
            status = s['status']
            if not status:
                # Not yet created — count as 0
                continue
            # dont_wait_for_delete: DELETE_IN_PROGRESS is an acceptable end state
            if dont_wait and status == 'DELETE_IN_PROGRESS':
                progress_sum += 100
                continue
            # keep_failed: failed stacks are intentionally kept, count as fully processed
            if keep_failed and status in ('CREATE_FAILED', 'UPDATE_FAILED',
                                          'CREATE_ROLLBACK_COMPLETE', 'ROLLBACK_COMPLETE',
                                          'CREATE_ROLLBACK_FAILED', 'ROLLBACK_FAILED'):
                progress_sum += 100
                continue
            # Any other IN_PROGRESS status — contribute a partial value
            if status in self._IN_PROGRESS_STATUSES:
                if status == 'DELETE_IN_PROGRESS':
                    # Create done (50) + delete midway (25) = 75
                    progress_sum += 75
                elif status in ('CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS'):
                    # Create midway: half of create_weight
                    progress_sum += create_weight // 2
                else:
                    # Rollback in progress: treat as create midway
                    progress_sum += create_weight // 2
                continue
            if no_delete:
                # Only create phase matters
                progress_sum += 100
            elif status == 'DELETE_COMPLETE':
                # Both create and delete phases done
                progress_sum += 100
            elif status == 'DELETE_FAILED':
                # Delete attempted but failed — count as fully processed
                progress_sum += 100
            elif status.startswith('DELETE_'):
                # Other delete states — create done, delete partly
                progress_sum += 65
            else:
                # Create phase done (CREATE_COMPLETE / CREATE_FAILED / ROLLBACK_*)
                progress_sum += create_weight

        self.progress = min(99, int(progress_sum / total))


class TestRunner:
    """Manages test runs - creation, execution, and tracking."""

    def __init__(self):
        self._runs: Dict[str, TestRun] = {}
        self._lock = asyncio.Lock()
        self._load_runs_from_disk()

    def _save_run_to_disk(self, run: TestRun):
        """Persist a single run's state to disk."""
        try:
            _RUNS_DIR.mkdir(parents=True, exist_ok=True)
            data = run.to_dict()
            run_file = _RUNS_DIR / f'{run.id}.json'
            with open(run_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as ex:
            LOG.warning(f'Failed to save run {run.id} to disk: {ex}')

    def _delete_run_from_disk(self, run_id: str):
        """Remove a run's persisted file from disk."""
        try:
            run_file = _RUNS_DIR / f'{run_id}.json'
            if run_file.exists():
                run_file.unlink()
        except Exception as ex:
            LOG.warning(f'Failed to delete run file {run_id}: {ex}')

    def _load_runs_from_disk(self):
        """Load all persisted runs from disk on startup."""
        if not _RUNS_DIR.exists():
            return
        for run_file in sorted(_RUNS_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(run_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                run = TestRun(
                    run_id=data.get('id', run_file.stem),
                    name=data.get('name', 'unknown'),
                    params=data.get('params', {}),
                )
                run.status = data.get('status', 'completed')
                run.progress = data.get('progress', 0)
                run.created_at = data.get('created_at', '')
                run.completed_at = data.get('completed_at')
                run.stacks = data.get('stacks', [])
                # Fix UTC timezone for persisted stack times (ROS API returns UTC
                # without 'Z' suffix; older runs may lack the fix applied in _update_progress).
                for _s in run.stacks:
                    if isinstance(_s, dict):
                        _s['create_time'] = _ensure_utc_suffix(_s.get('create_time', ''))
                        _s['status_time'] = _ensure_utc_suffix(_s.get('status_time', ''))
                run.error = data.get('error')
                run.report_path = Path(data['report_path']) if data.get('report_path') else None
                run.log_path = Path(data['log_path']) if data.get('log_path') else None
                run.credential_key_id = data.get('credential_key_id')
                # Mark incomplete runs as failed (server may have crashed mid-run)
                if run.status in ('pending', 'running'):
                    run.status = 'failed'
                    run.error = run.error or 'Server was restarted during test execution'
                self._runs[run.id] = run
            except Exception as ex:
                LOG.warning(f'Failed to load run from {run_file}: {ex}')
        if self._runs:
            LOG.info(f'Loaded {len(self._runs)} persisted run(s) from disk')

    def get_all_runs(self) -> List[dict]:
        """Get all test runs sorted by creation time (newest first)."""
        runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in runs]

    def get_run(self, run_id: str) -> Optional[dict]:
        """Get a specific test run (including logs)."""
        run = self._runs.get(run_id)
        if run and run.status not in ('completed', 'failed', 'cancelled'):
            run.update_stacks()
            return run.to_dict(include_logs=True)
        # For terminal states (or if not in memory), always reload from disk
        # to ensure we pick up mutations made by delete_run_stacks (which may
        # have run in a different process or after the in-memory cache became
        # stale).
        run = self._load_single_run_from_disk(run_id)
        if run:
            return run.to_dict(include_logs=True)
        return None

    def get_run_raw(self, run_id: str) -> Optional[TestRun]:
        """Get the raw TestRun object (not dict) for mutation operations."""
        return self._runs.get(run_id)

    def get_run_logs(self, run_id: str) -> str:
        """Return the raw CLI log text for a run."""
        run = self._runs.get(run_id)
        log_path = run.log_path if run else None
        if not log_path or not Path(log_path).exists():
            # Try to reconstruct from persisted state
            run = self._load_single_run_from_disk(run_id)
            log_path = run.log_path if run else None
        if not log_path or not Path(log_path).exists():
            return ''
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as ex:
            LOG.warning(f'Failed to read logs for run {run_id}: {ex}')
            return ''

    def _load_single_run_from_disk(self, run_id: str) -> Optional[TestRun]:
        """Load a single run from disk into memory."""
        run_file = _RUNS_DIR / f'{run_id}.json'
        if not run_file.exists():
            return None
        try:
            with open(run_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            run = TestRun(
                run_id=data.get('id', run_file.stem),
                name=data.get('name', 'unknown'),
                params=data.get('params', {}),
            )
            run.status = data.get('status', 'completed')
            run.progress = data.get('progress', 0)
            run.created_at = data.get('created_at', '')
            run.completed_at = data.get('completed_at')
            run.stacks = data.get('stacks', [])
            run.error = data.get('error')
            run.report_path = Path(data['report_path']) if data.get('report_path') else None
            run.log_path = Path(data['log_path']) if data.get('log_path') else None
            run.credential_key_id = data.get('credential_key_id')
            if run.status in ('pending', 'running'):
                run.status = 'failed'
                run.error = run.error or 'Server was restarted during test execution'
            self._runs[run.id] = run
            return run
        except Exception as ex:
            LOG.warning(f'Failed to load run {run_id} from disk: {ex}')
            return None

    async def start_test_run(self, params: dict, run_id: str = None) -> TestRun:
        """Start a new test run in the background."""
        run_id = run_id or uuid.uuid4().hex[:12]
        name = params.get('name', f'test-{run_id}')
        run = TestRun(run_id=run_id, name=name, params=params)
        self._runs[run_id] = run
        self._save_run_to_disk(run)
        # Clean up oldest output directories to prevent accumulation
        self._auto_cleanup_old_outputs()
        # Start test in background
        run._task = asyncio.create_task(self._execute_test(run))
        return run

    async def _execute_test(self, run: TestRun):
        """Execute the test and update status."""
        run.status = 'running'
        run.progress = 0
        try:
            params = run.params
            template = params.get('template')
            config_file = params.get('config_file')
            output_directory = params.get('output_directory', DEFAULT_OUTPUT_DIRECTORY)
            regions = params.get('regions')
            test_names = params.get('test_names')
            no_delete = params.get('no_delete', False)
            project_path = params.get('project_path')
            keep_failed = params.get('keep_failed', False)
            dont_wait_for_delete = params.get('dont_wait_for_delete', False)
            log_format = params.get('log_format')

            LOG.info(f'Starting test run: {run.id} - {run.name}')

            run.log_path = Path(output_directory) / 'run.log'
            with capture_iact3_logs(run.log_path):
                test = await StackTest.from_file(
                    template=template,
                    project_config_file=config_file,
                    no_delete=no_delete,
                    regions=regions,
                    project_path=project_path,
                    keep_failed=keep_failed,
                    dont_wait_for_delete=dont_wait_for_delete,
                    test_names=test_names,
                    output_directory=output_directory,
                    template_content=params.get('template_content'),
                )
                run._test = test
                run.report_path = test.report_path
                # Save a non-secret fingerprint of the credential used for this run
                # so that stack deletion can verify the same credential is active.
                if test.auth and test.auth.credential:
                    ak = getattr(test.auth.credential, 'access_key_id', '') or ''
                    run.credential_key_id = ak[-4:] if len(ak) >= 4 else ak

                # Run test (create stacks)
                async with test:
                    run.update_stacks()
                    # Generate report
                    await test.report(log_format)
                    run.update_stacks()

            run.completed_at = datetime.now().isoformat()
            run.update_stacks(force=True)   # Capture final stack states before saving
            run.progress = 100
            # Mark run as failed if any stack failed (validation error, create failed, etc.)
            any_stack_failed = any(
                not s.get('launch_succeeded', True)
                or 'fail' in (s.get('status', '')).lower()
                or 'rollback' in (s.get('status', '')).lower()
                for s in run.stacks
            )
            run.status = 'failed' if any_stack_failed else 'completed'
            self._save_run_to_disk(run)
            if any_stack_failed:
                LOG.info(f'Test run {run.id} finished with stack failures')
            else:
                LOG.info(f'Test run {run.id} completed successfully')

        except Exception as ex:
            run.status = 'failed'
            run.error = str(ex)
            run.completed_at = datetime.now().isoformat()
            run.update_stacks(force=True)   # Capture final stack states before saving
            self._save_run_to_disk(run)
            LOG.error(f'Test run {run.id} failed: {ex}', exc_info=True)

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a running test and wait for cleanup to finish."""
        run = self._runs.get(run_id)
        if not run:
            return False
        if run._task and not run._task.done():
            run._task.cancel()
            try:
                await run._task
            except asyncio.CancelledError:
                pass
            except Exception as ex:
                LOG.warning(f'Task cleanup for run {run_id} raised: {ex}')
            run.status = 'cancelled'
            run.completed_at = datetime.now().isoformat()
            run.update_stacks()
            self._save_run_to_disk(run)
            return True
        return False

    def delete_run(self, run_id: str) -> bool:
        """Delete a test run record and its output files."""
        run = self._runs.get(run_id)
        if not run:
            return False
        if run._task and not run._task.done():
            return False  # Can't delete a running test
        # Remove output directory for this run
        self._cleanup_run_output(run)
        del self._runs[run_id]
        self._delete_run_from_disk(run_id)
        return True

    def _cleanup_run_output(self, run: 'TestRun'):
        """Delete the output directory generated for a specific run."""
        if not run.report_path:
            return
        report_path = Path(run.report_path)
        # Safety: only delete paths that live under iact3_outputs/runs/
        try:
            output_runs_root = Path(DEFAULT_PROJECT_ROOT) / DEFAULT_OUTPUT_DIRECTORY / 'runs'
            report_path.resolve().relative_to(output_runs_root.resolve())
        except ValueError:
            LOG.warning(f'Skipping cleanup of run {run.id}: report_path {report_path} is outside safe root')
            return
        if report_path.exists():
            try:
                shutil.rmtree(report_path)
                LOG.info(f'Deleted output directory for run {run.id}: {report_path}')
            except Exception as ex:
                LOG.warning(f'Failed to delete output directory for run {run.id}: {ex}')

    def _auto_cleanup_old_outputs(self):
        """Keep only the _MAX_OUTPUT_RUNS most recent run output directories.

        This prevents iact3_outputs/runs/ from growing unboundedly when the user
        repeatedly runs tests without explicitly deleting old runs.
        """
        output_runs_root = Path(DEFAULT_PROJECT_ROOT) / DEFAULT_OUTPUT_DIRECTORY / 'runs'
        if not output_runs_root.exists():
            return
        run_dirs = sorted(
            [d for d in output_runs_root.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
        )
        # Remove oldest directories that exceed the limit
        to_delete = run_dirs[: max(0, len(run_dirs) - _MAX_OUTPUT_RUNS)]
        for old_dir in to_delete:
            # Only delete if no live run in memory references this path
            referenced = any(
                run.report_path and Path(run.report_path).resolve() == old_dir.resolve()
                for run in self._runs.values()
            )
            if not referenced:
                try:
                    shutil.rmtree(old_dir)
                    LOG.info(f'Auto-cleaned old output directory: {old_dir}')
                except Exception as ex:
                    LOG.warning(f'Failed to auto-clean {old_dir}: {ex}')
