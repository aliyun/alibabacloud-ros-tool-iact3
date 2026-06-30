 # -*- coding: utf-8 -*-
import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

from iact3.config import DEFAULT_CONFIG_FILE, DEFAULT_OUTPUT_DIRECTORY, DEFAULT_PROJECT_ROOT
from iact3.testing.ros_stack import StackTest
from iact3.report.generate_reports import ReportBuilder

LOG = logging.getLogger(__name__)

# Directory for persisting test run state across server restarts
_RUNS_DIR = Path(DEFAULT_PROJECT_ROOT) / '.iact3' / 'runs'


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
        self._test: Optional[StackTest] = None
        self._task: Optional[asyncio.Task] = None

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'progress': self.progress,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'stacks': self.stacks,
            'error': self.error,
            'params': self.params,
            'report_path': str(self.report_path) if self.report_path else None,
        }

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
                run.error = data.get('error')
                run.report_path = Path(data['report_path']) if data.get('report_path') else None
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
        """Get a specific test run."""
        run = self._runs.get(run_id)
        if run and run.status not in ('completed', 'failed', 'cancelled'):
            run.update_stacks()
            return run.to_dict()
        # For terminal states (or if not in memory), always reload from disk
        # to ensure we pick up mutations made by delete_run_stacks (which may
        # have run in a different process or after the in-memory cache became
        # stale).
        run = self._load_single_run_from_disk(run_id)
        if run:
            return run.to_dict()
        return None

    def get_run_raw(self, run_id: str) -> Optional[TestRun]:
        """Get the raw TestRun object (not dict) for mutation operations."""
        return self._runs.get(run_id)

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
            if run.status in ('pending', 'running'):
                run.status = 'failed'
                run.error = run.error or 'Server was restarted during test execution'
            self._runs[run.id] = run
            return run
        except Exception as ex:
            LOG.warning(f'Failed to load run {run_id} from disk: {ex}')
            return None

    async def start_test_run(self, params: dict) -> TestRun:
        """Start a new test run in the background."""
        run_id = uuid.uuid4().hex[:12]
        name = params.get('name', f'test-{run_id}')
        run = TestRun(run_id=run_id, name=name, params=params)
        self._runs[run_id] = run
        self._save_run_to_disk(run)

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

            # Run test (create stacks)
            async with test:
                run.update_stacks()
                # Generate report
                await test.report(log_format)
                run.update_stacks()

            run.status = 'completed'
            run.progress = 100
            run.completed_at = datetime.now().isoformat()
            run.update_stacks(force=True)   # Capture final stack states before saving
            self._save_run_to_disk(run)
            LOG.info(f'Test run {run.id} completed successfully')

        except Exception as ex:
            run.status = 'failed'
            run.error = str(ex)
            run.completed_at = datetime.now().isoformat()
            run.update_stacks(force=True)   # Capture final stack states before saving
            self._save_run_to_disk(run)
            LOG.error(f'Test run {run.id} failed: {ex}', exc_info=True)

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a running test."""
        run = self._runs.get(run_id)
        if not run:
            return False
        if run._task and not run._task.done():
            run._task.cancel()
            run.status = 'cancelled'
            run.completed_at = datetime.now().isoformat()
            run.update_stacks()
            self._save_run_to_disk(run)
            return True
        return False

    def delete_run(self, run_id: str) -> bool:
        """Delete a test run record."""
        run = self._runs.get(run_id)
        if not run:
            return False
        if run._task and not run._task.done():
            return False  # Can't delete a running test
        del self._runs[run_id]
        self._delete_run_from_disk(run_id)
        return True
