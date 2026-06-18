# -*- coding: utf-8 -*-
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

from aiohttp import web
from Tea.exceptions import TeaException

from iact3.config import TemplateConfig, BaseConfig, DEFAULT_CONFIG_FILE, DEFAULT_PROJECT_ROOT, PROJECT, REGIONS, TEMPLATE_CONFIG, TEMPLATE_BODY
from iact3.plugin.ros import StackPlugin
from iact3.testing.ros_stack import StackTest
from iact3.util import yaml as iact3_yaml, CustomSafeLoader

LOG = logging.getLogger(__name__)

# Unified directory for web-managed files
_UPLOAD_DIR = Path(DEFAULT_PROJECT_ROOT) / '.iact3'
_PROJECTS_DIR = _UPLOAD_DIR / 'projects'
_HISTORY_DIR = _UPLOAD_DIR / 'history'

# Settings file for persistent web configuration
_SETTINGS_FILE = Path('.iact3_web_settings.json')

ALLOWED_TEMPLATE_EXTENSIONS = {'.json', '.yaml', '.yml', '.tf'}

# --- Example content for new users ---
_EXAMPLE_TEMPLATE = """ROSTemplateFormatVersion: '2015-09-01'
Description: Simple VPC template
Parameters:
  VpcName:
    Type: String
    Description: VPC Name
    Default: my-vpc
  CidrBlock:
    Type: String
    Description: VPC CIDR Block
    Default: '10.0.0.0/16'
Resources:
  Vpc:
    Type: ALIYUN::ECS::VPC
    Properties:
      CidrBlock:
        Ref: CidrBlock
      VpcName:
        Ref: VpcName
Outputs:
  VpcId:
    Value:
      Fn::GetAtt:
        - Vpc
        - VpcId
"""

_EXAMPLE_CONFIG = """project:
  name: my-project
  template_config:
    template_location: ''
tests:
  default:
    regions:
      - cn-hangzhou
    parameters:
      VpcName: my-vpc
      CidrBlock: '10.0.0.0/16'
"""


def _sync_project_name_in_config(config_yaml, project_name):
    """Inject/update project.name in config YAML content."""
    if not config_yaml or not project_name:
        return config_yaml
    lines = config_yaml.split('\n')
    in_project = False
    name_updated = False
    name_inserted = False
    result = []

    for line in lines:
        trimmed = line.strip()
        if re.match(r'^project\s*:', line):
            in_project = True
            result.append(line)
            continue
        if in_project and trimmed and not line.startswith(' ') and not line.startswith('\t') and trimmed != '---':
            if not name_inserted:
                result.append(f'  name: {project_name}')
                name_inserted = True
                name_updated = True
            in_project = False
        if in_project and re.match(r'^\s+name\s*:', line):
            result.append(f'  name: {project_name}')
            name_updated = True
            name_inserted = True
            continue
        result.append(line)

    if in_project and not name_inserted:
        result.append(f'  name: {project_name}')
        name_updated = True

    if not name_updated:
        if result and result[-1].strip():
            result.append('')
        result.append('project:')
        result.append(f'  name: {project_name}')

    return '\n'.join(result)


def _resolve_project_inputs(params):
    """Resolve template/config content from params or saved project.
    Priority: editor content > saved project.
    Returns: (template_content: str|None, config_content: str|None)
    """
    project_name = params.get('project_name')
    template_content = params.get('template_content')
    config_content = params.get('config_content')
    has_template = 'template_content' in params
    has_config = 'config_content' in params

    # Load saved project as fallback (only when editor didn't send both fields)
    saved = None
    if project_name and not (has_template and has_config):
        project_file = _PROJECTS_DIR / f'{project_name}.json'
        if project_file.exists():
            try:
                with open(project_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
            except Exception:
                pass

    # Resolve template content
    if has_template:
        resolved_tpl = template_content  # may be empty string
    elif saved and saved.get('template'):
        resolved_tpl = saved['template']
    else:
        resolved_tpl = None

    # Resolve config content
    if has_config:
        resolved_cfg = config_content
    elif saved and saved.get('config'):
        resolved_cfg = saved['config']
    else:
        resolved_cfg = None

    # Sync project.name into config content
    if resolved_cfg and project_name:
        resolved_cfg = _sync_project_name_in_config(resolved_cfg, project_name)

    LOG.debug(
        '[_resolve_project_inputs] project=%s tpl_len=%d cfg_len=%d',
        project_name,
        len(resolved_tpl) if resolved_tpl else 0,
        len(resolved_cfg) if resolved_cfg else 0,
    )
    return resolved_tpl, resolved_cfg


def _ensure_tests_section(config_content, regions=None, project_name=None):
    """Ensure config YAML has a `tests:` section.
    If missing, inject a minimal default test using the provided regions.
    If regions is also absent, leave config as-is (downstream will fail with a clear error).
    """
    if not config_content or not config_content.strip():
        # No config at all — build a minimal one from scratch
        if not regions:
            return config_content
        lines = []
        if project_name:
            lines += ['project:', f'  name: {project_name}', '']
        lines += ['tests:', '  default:', '    regions:']
        for r in regions.split(','):
            r = r.strip()
            if r:
                lines.append(f'      - {r}')
        return '\n'.join(lines) + '\n'

    # Check whether tests: section already exists
    try:
        parsed = iact3_yaml.safe_load(config_content)
    except Exception:
        parsed = {}
    if parsed and parsed.get('tests'):
        return config_content  # already has tests, leave untouched

    # Inject a minimal tests: section
    if not regions:
        return config_content  # no regions to inject — leave as-is
    region_list = [r.strip() for r in regions.split(',') if r.strip()]
    if not region_list:
        return config_content

    lines = config_content.rstrip().split('\n')
    lines.append('')
    lines.append('tests:')
    lines.append('  default:')
    lines.append('    regions:')
    for r in region_list:
        lines.append(f'      - {r}')
    return '\n'.join(lines) + '\n'


def _write_current_files(template_content, config_content):
    """Write content to .iact3/_current/ temp files for tools that require file paths.
    Returns: (template_path: str|None, config_path: str|None)
    """
    current_dir = _UPLOAD_DIR / '_current'
    current_dir.mkdir(parents=True, exist_ok=True)
    tpl_path = cfg_path = None
    if template_content:
        p = current_dir / 'template.yaml'
        p.write_text(template_content, encoding='utf-8')
        tpl_path = str(p.relative_to(DEFAULT_PROJECT_ROOT))
    if config_content:
        p = current_dir / 'config.yml'
        p.write_text(config_content, encoding='utf-8')
        cfg_path = str(p.relative_to(DEFAULT_PROJECT_ROOT))
    return tpl_path, cfg_path


def _save_history(project_name, analysis_type, result, error=None):
    """Save analysis result to history."""
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        # Sanitize result for JSON serialization
        def _sanitize(obj):
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            if isinstance(obj, dict):
                return {str(k): _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_sanitize(v) for v in obj]
            return str(obj)
        entry = {
            'id': uuid.uuid4().hex[:12],
            'type': analysis_type,
            'timestamp': str(time.time()),
            'result': _sanitize(result) if isinstance(result, (dict, list)) else str(result),
            'error': error
        }
        if project_name:
            entry['project_name'] = project_name
        history_file = _HISTORY_DIR / f"{entry['id']}.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(entry, f, ensure_ascii=False, indent=2, default=str)
        return entry['id']
    except Exception as ex:
        LOG.warning(f'Failed to save history: {ex}', exc_info=True)
        return None


def setup_routes(app: web.Application):
    """Register all API routes."""
    runner = app['runner']

    # --- API: Test Runs ---

    async def list_runs(request):
        """GET /api/runs - List all test runs."""
        return web.json_response({'runs': runner.get_all_runs()})

    async def get_run(request):
        """GET /api/runs/{run_id} - Get a specific test run."""
        run_id = request.match_info['run_id']
        run = runner.get_run(run_id)
        if not run:
            return web.json_response({'error': 'Run not found'}, status=404)
        return web.json_response(run)

    async def start_run(request):
        """POST /api/runs - Start a new test run."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        if not params:
            return web.json_response({'error': 'Request body is required'}, status=400)

        # Resolve content, then write to temp files for StackTest.from_file()
        template_content, config_content = _resolve_project_inputs(params)
        # Ensure the config has a `tests:` section so StackTest.from_file
        # creates actual test cases. Inject one using the provided regions when absent.
        regions_str = params.get('regions') or ''
        project_name_for_cfg = params.get('project_name') or ''
        config_content = _ensure_tests_section(config_content, regions_str, project_name_for_cfg)
        tpl_path, cfg_path = _write_current_files(template_content, config_content)
        if tpl_path:
            params['template'] = tpl_path
        if cfg_path:
            params['config_file'] = cfg_path
        if template_content:
            params['template_content'] = template_content

        try:
            run = await runner.start_test_run(params)
            return web.json_response(run.to_dict(), status=201)
        except Exception as ex:
            LOG.error(f'Failed to start test run: {ex}', exc_info=True)
            return web.json_response({'error': str(ex)}, status=500)

    async def cancel_run(request):
        """POST /api/runs/{run_id}/cancel - Cancel a test run."""
        run_id = request.match_info['run_id']
        ok = await runner.cancel_run(run_id)
        if not ok:
            return web.json_response({'error': 'Cannot cancel run'}, status=400)
        return web.json_response({'status': 'cancelled'})

    async def delete_run(request):
        """DELETE /api/runs/{run_id} - Delete a test run."""
        run_id = request.match_info['run_id']
        ok = runner.delete_run(run_id)
        if not ok:
            return web.json_response({'error': 'Cannot delete run'}, status=400)
        return web.json_response({'status': 'deleted'})

    async def delete_run_stacks(request):
        """POST /api/runs/{run_id}/delete-stacks - Delete stacks created by a test run."""
        run_id = request.match_info['run_id']
        run = runner.get_run_raw(run_id)
        if not run:
            # Try to load from disk in case server was restarted
            run = runner._load_single_run_from_disk(run_id)
        if not run:
            return web.json_response({'error': 'Run not found', 'code': 'RUN_NOT_FOUND'}, status=404)

        stacks = run.stacks or []
        if not stacks:
            return web.json_response({'error': 'No stacks found for this run', 'code': 'NO_STACKS'}, status=400)

        # Filter out stacks that are already deleted or deleting
        stacks_to_delete = [s for s in stacks if s.get('stack_id') and not s.get('status', '').startswith('DELETE')]
        if not stacks_to_delete:
            return web.json_response({'error': 'No deletable stacks found', 'code': 'NO_DELETABLE_STACKS'}, status=400)

        try:
            from iact3.cli_modules.list import List
            from iact3.plugin.ros import StackPlugin
            credential = List.get_credential()

            results = []
            errors = []

            # Group by region to minimize plugin creation
            region_groups = {}
            for s in stacks_to_delete:
                region = s.get('region')
                if region:
                    region_groups.setdefault(region, []).append(s['stack_id'])

            for region, stack_ids in region_groups.items():
                plugin = StackPlugin(region_id=region, credential=credential)
                for stack_id in stack_ids:
                    try:
                        await plugin.delete_stack(stack_id)
                        # Update stack status in run state so UI reflects deletion
                        for s in run.stacks:
                            if s.get('stack_id') == stack_id:
                                s['status'] = 'DELETE_COMPLETE'
                        results.append({'stack_id': stack_id, 'region': region, 'status': 'deleted'})
                    except Exception as ex:
                        errors.append({'stack_id': stack_id, 'region': region, 'error': str(ex)})

            # Persist updated stack statuses
            runner._save_run_to_disk(run)

            return web.json_response({
                'deleted': len(results),
                'errors': len(errors),
                'details': results + errors,
            })
        except Exception as ex:
            LOG.error(f'Failed to delete stacks for run {run_id}: {ex}', exc_info=True)
            return web.json_response({'error': str(ex)}, status=500)

    # --- API: Validate ---
    
    async def validate_template(request):
        """POST /api/validate - Validate a template."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
    
        template_content, config_content = _resolve_project_inputs(params)
        regions = params.get('regions')
        template_args = {}  # Initialize for error logging

        LOG.warning('[validate] RAW params keys=%s project=%s tpl_content_len=%d cfg_content_len=%d',
            list(params.keys()),
            params.get('project_name'),
            len(params.get('template_content', '') or ''),
            len(params.get('config_content', '') or ''),
        )
        LOG.warning('[validate] RESOLVED tpl_len=%d cfg_len=%d',
            len(template_content) if template_content else 0,
            len(config_content) if config_content else 0,
        )

        if not template_content:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'result': 'invalid',
                 'error': f'模板内容为空，无法校验。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )
    
        try:
            args = {TEMPLATE_CONFIG: {TEMPLATE_BODY: template_content}}
            if regions:
                args[REGIONS] = regions.split(',')

            if config_content:
                # Write config to temp file so BaseConfig.create can parse it
                _, cfg_path = _write_current_files(None, config_content)
                base_config = BaseConfig.create(
                    project_config_file=cfg_path or DEFAULT_CONFIG_FILE,
                    args={PROJECT: args},
                    project_path=DEFAULT_PROJECT_ROOT,
                )
                if base_config.tests:
                    test_config = next(iter(base_config.tests.values()))
                    credential = test_config.auth.credential
                else:
                    # config has no tests section, try project-level credential
                    credential = base_config.project.auth.credential
                # Always build a fresh TemplateConfig with template_body to avoid lru_cache stale hits
                template_config = TemplateConfig(template_body=template_content)
                template_args = template_config.generate_template_args()
                LOG.warning('[validate] with-config path: tc=%s ta_keys=%s tpl_body_len=%d',
                    template_config, list(template_args.keys()),
                    len(template_args.get('template_body', '') or ''))
                plugin = StackPlugin(region_id=None, credential=credential)
            else:
                template_config = TemplateConfig(template_body=template_content)
                template_args = template_config.generate_template_args()
                LOG.warning('[validate] no-config path: tc=%s ta_keys=%s tpl_body_len=%d',
                    template_config, list(template_args.keys()),
                    len(template_args.get('template_body', '') or ''))
                plugin = StackPlugin(region_id=None, credential=None)

            result = await plugin.validate_template(**template_args)
            _save_history(params.get('project_name'), 'validate', {'result': 'valid', 'details': result})
            return web.json_response({'result': 'valid', 'details': result})
        except Exception as ex:
            import traceback
            tpl_body = template_args.get('template_body', '')
            LOG.error('[validate] FAILED. template_body len=%d, error_type=%s error=%s\nTraceback:\n%s',
                len(tpl_body), type(ex).__name__, ex, traceback.format_exc())
            _save_history(params.get('project_name'), 'validate', None, error=str(ex))
            err_msg = str(ex) or f'{type(ex).__name__}: (no message)'
            return web.json_response({'result': 'invalid', 'error': err_msg}, status=400)

    # --- API: Cost ---

    async def estimate_cost(request):
        """POST /api/cost - Estimate template cost."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
    
        template_content, config_content = _resolve_project_inputs(params)
        if not template_content:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'error': f'模板内容为空，无法估算费用。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )
        try:
            _, cfg_path = _write_current_files(None, config_content)
            test = await StackTest.from_file(
                template=None,
                project_config_file=cfg_path,
                regions=params.get('regions'),
                template_content=template_content,
            )
            await StackTest.get_stacks_price(test)

            prices = []
            if test.stacker:
                for stack in test.stacker.stacks:
                    prices.append({
                        'test_name': stack.test_name,
                        'region': stack.region,
                        'price': stack.template_price,
                        'status': stack.status,
                        'error': _format_stack_error(stack) if not stack.template_price else None,
                    })
            _save_history(params.get('project_name'), 'cost', {'prices': prices})
            return web.json_response({'prices': prices})
        except TeaException as ex:
            _save_history(params.get('project_name'), 'cost', None, error=_format_tea_exception(ex))
            return web.json_response({'error': _format_tea_exception(ex)}, status=400)
        except Exception as ex:
            _save_history(params.get('project_name'), 'cost', None, error=str(ex))
            return web.json_response({'error': str(ex)}, status=500)

    # --- API: Preview ---

    async def preview_resources(request):
        """POST /api/preview - Preview template resources."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
    
        template_content, config_content = _resolve_project_inputs(params)
        if not template_content:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'error': f'模板内容为空，无法预览资源。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )
        try:
            _, cfg_path = _write_current_files(None, config_content)
            test = await StackTest.from_file(
                template=None,
                project_config_file=cfg_path,
                regions=params.get('regions'),
                template_content=template_content,
            )
            await StackTest.preview_stacks_result(test)

            previews = []
            if test.stacker:
                for stack in test.stacker.stacks:
                    previews.append({
                        'test_name': stack.test_name,
                        'region': stack.region,
                        'resources': stack.preview_result,
                        'status': stack.status,
                        'error': _format_stack_error(stack) if not stack.preview_result else None,
                    })
            _save_history(params.get('project_name'), 'preview', {'previews': previews})
            return web.json_response({'previews': previews})
        except TeaException as ex:
            _save_history(params.get('project_name'), 'preview', None, error=_format_tea_exception(ex))
            return web.json_response({'error': _format_tea_exception(ex)}, status=400)
        except Exception as ex:
            _save_history(params.get('project_name'), 'preview', None, error=str(ex))
            return web.json_response({'error': str(ex)}, status=500)

    # --- API: Policy ---

    async def generate_policy(request):
        """POST /api/policy - Generate template policy."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
    
        template_content, config_content = _resolve_project_inputs(params)
        if not template_content:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'error': f'模板内容为空，无法生成策略。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )
    
        try:
            args = {TEMPLATE_CONFIG: {TEMPLATE_BODY: template_content}}
            if config_content:
                _, cfg_path = _write_current_files(None, config_content)
                base_config = BaseConfig.create(
                    project_config_file=cfg_path or DEFAULT_CONFIG_FILE,
                    args={PROJECT: args},
                    project_path=DEFAULT_PROJECT_ROOT,
                )
                if base_config.tests:
                    test_config = next(iter(base_config.tests.values()))
                    credential = test_config.auth.credential
                else:
                    credential = base_config.project.auth.credential
                # Always build fresh TemplateConfig with template_body
                template_config = TemplateConfig(template_body=template_content)
                template_args = template_config.generate_template_args()
                plugin = StackPlugin(region_id=None, credential=credential)
            else:
                template_config = TemplateConfig(template_body=template_content)
                template_args = template_config.generate_template_args()
                plugin = StackPlugin(region_id=None, credential=None)

            policy = await plugin.generate_template_policy(**template_args)
            _save_history(params.get('project_name'), 'policy', {'policy': policy})
            return web.json_response({'policy': policy})
        except Exception as ex:
            _save_history(params.get('project_name'), 'policy', None, error=str(ex))
            return web.json_response({'error': str(ex)}, status=500)

    # --- API: Report files ---

    async def list_reports(request):
        """GET /api/reports - List all output files with details."""
        output_dir = Path('iact3_outputs')
        if not output_dir.exists():
            return web.json_response({'reports': [], 'total_size': 0})

        reports = []
        total_size = 0
        for f in sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not f.is_file():
                continue
            stat = f.stat()
            total_size += stat.st_size

            # Determine file category
            if f.suffix == '.html':
                category = 'report'
            elif f.suffix == '.json' and f.name.endswith('-result.json'):
                category = 'result'
            elif f.suffix == '.txt':
                category = 'log'
            elif 'hook' in f.name.lower():
                category = 'hook'
            else:
                category = 'other'

            reports.append({
                'name': f.name,
                'type': f.suffix.lstrip('.'),
                'category': category,
                'size': stat.st_size,
                'modified': stat.st_mtime,
            })
        return web.json_response({'reports': reports, 'total_size': total_size})

    async def get_report_file(request):
        """GET /api/reports/{filename} - Get a specific report file."""
        filename = request.match_info['filename']
        output_dir = Path('iact3_outputs')
        file_path = output_dir / filename

        if not file_path.exists() or not file_path.is_file():
            return web.json_response({'error': 'File not found'}, status=404)

        # Prevent path traversal
        try:
            file_path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            return web.json_response({'error': 'Invalid path'}, status=403)

        if file_path.suffix == '.html':
            return web.FileResponse(file_path)
        elif file_path.suffix == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return web.json_response(data)
        elif file_path.suffix == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return web.Response(text=content, content_type='text/plain')
        else:
            return web.FileResponse(file_path)

    async def get_report_raw(request):
        """GET /api/reports/{filename}/raw - Get raw file content as text."""
        filename = request.match_info['filename']
        output_dir = Path('iact3_outputs')
        file_path = output_dir / filename

        if not file_path.exists() or not file_path.is_file():
            return web.json_response({'error': 'File not found'}, status=404)

        try:
            file_path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            return web.json_response({'error': 'Invalid path'}, status=403)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Pretty-print JSON files
            if file_path.suffix == '.json':
                try:
                    content = json.dumps(json.loads(content), indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass
            return web.json_response({
                'filename': filename,
                'content': content,
                'type': file_path.suffix.lstrip('.'),
            })
        except UnicodeDecodeError:
            return web.json_response({'error': 'Binary file cannot be previewed'}, status=400)

    async def delete_report(request):
        """DELETE /api/reports/{filename} - Delete a single report file."""
        filename = request.match_info['filename']
        output_dir = Path('iact3_outputs')
        file_path = output_dir / filename

        if not file_path.exists() or not file_path.is_file():
            return web.json_response({'error': 'File not found'}, status=404)

        try:
            file_path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            return web.json_response({'error': 'Invalid path'}, status=403)

        size = file_path.stat().st_size
        file_path.unlink()
        LOG.info(f'Deleted report file: {filename} ({size} bytes)')
        return web.json_response({'deleted': filename, 'size': size})

    async def cleanup_reports(request):
        """POST /api/reports/cleanup - Batch cleanup output files.

        Body JSON options:
          - mode: "all" | "older_than" | "keep_last"
          - days: int (for "older_than" mode)
          - keep: int (for "keep_last" mode, number of newest files to keep)
        """
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        mode = params.get('mode', 'all')
        output_dir = Path('iact3_outputs')
        if not output_dir.exists():
            return web.json_response({'deleted': 0, 'freed': 0})

        all_files = [f for f in output_dir.iterdir() if f.is_file()]
        to_delete = []

        if mode == 'all':
            to_delete = all_files

        elif mode == 'older_than':
            import time
            days = params.get('days', 7)
            cutoff = time.time() - days * 86400
            to_delete = [f for f in all_files if f.stat().st_mtime < cutoff]

        elif mode == 'keep_last':
            keep = params.get('keep', 10)
            sorted_files = sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True)
            to_delete = sorted_files[keep:]

        else:
            return web.json_response({'error': f'Unknown mode: {mode}'}, status=400)

        deleted_count = 0
        freed_bytes = 0
        for f in to_delete:
            try:
                size = f.stat().st_size
                f.unlink()
                deleted_count += 1
                freed_bytes += size
            except OSError as ex:
                LOG.warning(f'Failed to delete {f.name}: {ex}')

        LOG.info(f'Cleanup ({mode}): deleted {deleted_count} files, freed {freed_bytes} bytes')
        return web.json_response({
            'deleted': deleted_count,
            'freed': freed_bytes,
        })

    # --- API: File Upload (saves to type-based subdirectory) ---

    async def upload_template(request):
        """POST /api/upload?type=template|config - Upload a file to type-based subdirectory."""
        file_type = request.query.get('type', 'template')
        sub_dir = 'configs' if file_type == 'config' else 'templates'
        target_dir = _UPLOAD_DIR / sub_dir

        reader = await request.multipart()
        field = await reader.next()

        if not field or field.name != 'file':
            return web.json_response({'error': 'No file field found'}, status=400)

        filename = field.filename or 'uploaded_template'
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_TEMPLATE_EXTENSIONS:
            return web.json_response(
                {'error': f'Unsupported file type "{suffix}". Allowed: {", ".join(sorted(ALLOWED_TEMPLATE_EXTENSIONS))}'},
                status=400
            )

        # Save to type-based subdirectory with a unique name to avoid conflicts
        target_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f'{uuid.uuid4().hex[:8]}_{filename}'
        file_path = target_dir / unique_name

        size = 0
        max_size = 5 * 1024 * 1024  # 5 MB limit
        with open(file_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    file_path.unlink(missing_ok=True)
                    return web.json_response({'error': 'File too large (max 5MB)'}, status=400)
                f.write(chunk)

        LOG.info(f'Uploaded {file_type}: {filename} -> {file_path}')
        return web.json_response({
            'path': str(file_path),
            'filename': filename,
            'size': size,
            'type': file_type,
        })

    # --- API: Templates List & Delete (with type filter) ---

    async def list_templates(request):
        """GET /api/templates?type=template|config - List saved files by type."""
        file_type = request.query.get('type', 'template')
        sub_dir = 'configs' if file_type == 'config' else 'templates'
        target_dir = _UPLOAD_DIR / sub_dir

        files = []
        if target_dir.exists():
            for f in sorted(target_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.is_file() and f.suffix.lower() in ALLOWED_TEMPLATE_EXTENSIONS:
                    try:
                        stat = f.stat()
                        files.append({
                            'name': f.name,
                            'path': str(f),
                            'size': stat.st_size,
                            'extension': f.suffix.lower(),
                            'mtime': stat.st_mtime,
                        })
                    except Exception:
                        pass
        return web.json_response({'templates': files})

    async def delete_saved_file(request):
        """DELETE /api/templates/{filename}?type=template|config - Delete a saved file."""
        filename = request.match_info['filename']
        file_type = request.query.get('type', 'template')
        sub_dir = 'configs' if file_type == 'config' else 'templates'
        target_dir = _UPLOAD_DIR / sub_dir

        # Security: prevent path traversal
        file_path = (target_dir / filename).resolve()
        try:
            file_path.relative_to(target_dir.resolve())
        except ValueError:
            return web.json_response({'error': 'Invalid path'}, status=403)

        if not file_path.exists() or not file_path.is_file():
            return web.json_response({'error': 'File not found'}, status=404)

        size = file_path.stat().st_size
        file_path.unlink()
        LOG.info(f'Deleted saved {file_type}: {filename} ({size} bytes)')
        return web.json_response({'deleted': filename, 'type': file_type, 'size': size})

    # --- Helpers ---

    _UNKNOWN_PARAM_RE = re.compile(r'The Parameter \((\w+)\) was not defined in template')

    def _format_tea_exception(ex: TeaException) -> str:
        """Format TeaException with user-friendly messages."""
        code = getattr(ex, 'code', '') or ''
        message = getattr(ex, 'message', '') or str(ex)

        if code == 'UnknownUserParameter':
            match = _UNKNOWN_PARAM_RE.search(message)
            param_name = match.group(1) if match else 'unknown'
            return (
                f'Parameter "{param_name}" in config is not defined in the template. '
                f'Please check that the config file parameters match the template parameters, '
                f'or specify a correct template via the "Template Path" field.'
            )
        if code == 'TemplateNotFound':
            return 'Template not found. Please provide a valid template path.'
        if code in ('InvalidTemplateBody', 'InvalidTemplate'):
            return f'Invalid template: {message}'

        return f'[{code}] {message}' if code else message

    def _format_stack_error(stack) -> str:
        """Format a stack's error status_reason for display."""
        reason = stack.status_reason or ''
        code = stack.status or ''

        if code == 'UnknownUserParameter':
            match = _UNKNOWN_PARAM_RE.search(reason)
            param_name = match.group(1) if match else 'unknown'
            return (
                f'Parameter "{param_name}" is not defined in the template. '
                f'Check config parameters vs template parameters.'
            )
        return reason

    # --- API: Settings ---

    async def get_settings(request):
        """GET /api/settings - Get saved settings (credentials masked for security)."""
        settings = {}
        if _SETTINGS_FILE.exists():
            try:
                with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except Exception:
                settings = {}

        masked = dict(settings)
        ak = masked.get('access_key_id', '')
        sk = masked.get('access_key_secret', '')
        masked['access_key_id'] = ('****' + ak[-4:]) if ak and len(ak) > 4 else ('configured' if ak else '')
        masked['access_key_secret'] = 'configured' if sk else ''
        masked['credentials_set'] = bool(ak and sk)
        return web.json_response({'settings': masked})

    async def save_settings(request):
        """POST /api/settings - Save settings and apply credentials to env vars."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        # Load existing settings to merge unchanged credential fields
        existing = {}
        if _SETTINGS_FILE.exists():
            try:
                with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                pass

        settings = {
            'access_key_id':     params.get('access_key_id',     existing.get('access_key_id', '')),
            'access_key_secret': params.get('access_key_secret', existing.get('access_key_secret', '')),
            'security_token':    params.get('security_token',    ''),
            'regions':           params.get('regions',           ''),
        }

        # If user submits masked AK/SK (unchanged), keep the saved value
        if settings['access_key_id'].startswith('****'):
            settings['access_key_id'] = existing.get('access_key_id', '')
        if settings['access_key_secret'] == 'configured':
            settings['access_key_secret'] = existing.get('access_key_secret', '')

        try:
            with open(_SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2)
        except Exception as ex:
            return web.json_response({'error': f'Failed to save settings: {ex}'}, status=500)

        _apply_credentials_to_env(settings)
        LOG.info('Settings saved and credentials applied to environment.')
        return web.json_response({'status': 'ok', 'credentials_set': bool(settings['access_key_id'] and settings['access_key_secret'])})

    def _apply_credentials_to_env(settings=None):
        """Apply saved credentials to environment variables for SDK default chain."""
        if settings is None:
            if not _SETTINGS_FILE.exists():
                return
            try:
                with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except Exception:
                return

        ak = settings.get('access_key_id', '')
        sk = settings.get('access_key_secret', '')
        token = settings.get('security_token', '')
        if ak:
            os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'] = ak
        if sk:
            os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'] = sk
        if token:
            os.environ['ALIBABA_CLOUD_SECURITY_TOKEN'] = token

        # CRITICAL: auth_util caches env vars at import time as module-level variables.
        # Setting os.environ alone is NOT enough - we must also update the cached values.
        try:
            from alibabacloud_credentials.utils import auth_util
            if ak:
                auth_util.environment_access_key_id = ak
            if sk:
                auth_util.environment_access_key_secret = sk
        except ImportError:
            pass

        if ak or sk:
            LOG.info(f'Credentials applied to env (AK: {ak[:4]}...{ak[-4:]})' if len(ak) > 8 else 'Credentials applied to env')

    # Load saved settings into env vars on server startup
    _apply_credentials_to_env()

    # --- API: Update template location in .iact3.yml ---

    async def update_config_template(request):
        """POST /api/config/template-path - Update template_location in .iact3.yml."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        template_path = params.get('template_path', '').strip()
        config_file = params.get('config_file', DEFAULT_CONFIG_FILE)

        if not template_path:
            return web.json_response({'error': 'Missing template_path'}, status=400)

        config_path = DEFAULT_PROJECT_ROOT / config_file
        try:
            if config_path.is_file():
                with open(str(config_path), 'r', encoding='utf-8') as f:
                    config = iact3_yaml.load(f, Loader=CustomSafeLoader) or {}
            else:
                config = {}

            # Ensure nested structure exists
            if 'project' not in config:
                config['project'] = {}
            if 'template_config' not in config.get('project', {}):
                config['project']['template_config'] = {}
            config['project']['template_config']['template_location'] = template_path

            import yaml
            with open(str(config_path), 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            LOG.info(f'Updated template_location in {config_file} to: {template_path}')
            return web.json_response({'status': 'ok', 'template_path': template_path})
        except Exception as ex:
            return web.json_response({'error': str(ex)}, status=500)

    # --- API: File Read/Write ---

    async def read_file(request):
        """GET /api/file?path=xxx - Read a file's content."""
        file_path = request.query.get('path', '').strip()
        if not file_path:
            return web.json_response({'error': 'Missing path parameter'}, status=400)

        # Resolve path relative to project root
        resolved = Path(file_path)
        if not resolved.is_absolute():
            resolved = (DEFAULT_PROJECT_ROOT / resolved).resolve()

        # Security: prevent path traversal outside allowed dirs
        resolved_str = str(resolved)
        project_str = str(DEFAULT_PROJECT_ROOT.resolve())
        home_str = str(Path.home().resolve())
        upload_str = str(_UPLOAD_DIR.resolve())
        if not (resolved_str.startswith(project_str) or
                resolved_str.startswith(home_str) or
                resolved_str.startswith(upload_str)):
            return web.json_response({'error': 'Access denied: path outside allowed directories'}, status=403)

        if not resolved.exists():
            return web.json_response({'error': f'File not found: {file_path}'}, status=404)
        if not resolved.is_file():
            return web.json_response({'error': f'Not a file: {file_path}'}, status=400)

        try:
            content = resolved.read_text(encoding='utf-8')
            ext = resolved.suffix.lower()
            size = resolved.stat().st_size
            return web.json_response({
                'path': file_path,
                'resolved_path': resolved_str,
                'content': content,
                'extension': ext,
                'size': size,
            })
        except UnicodeDecodeError:
            return web.json_response({'error': 'File is not a text file'}, status=400)
        except Exception as ex:
            return web.json_response({'error': str(ex)}, status=500)

    async def write_file(request):
        """POST /api/file - Save file content. Body: {path, content}."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        file_path = params.get('path', '').strip()
        content = params.get('content', '')
        if not file_path:
            return web.json_response({'error': 'Missing path parameter'}, status=400)

        # Resolve path
        resolved = Path(file_path)
        if not resolved.is_absolute():
            resolved = (DEFAULT_PROJECT_ROOT / resolved).resolve()

        # Security check
        resolved_str = str(resolved)
        project_str = str(DEFAULT_PROJECT_ROOT.resolve())
        home_str = str(Path.home().resolve())
        upload_str = str(_UPLOAD_DIR.resolve())
        if not (resolved_str.startswith(project_str) or
                resolved_str.startswith(home_str) or
                resolved_str.startswith(upload_str)):
            return web.json_response({'error': 'Access denied: path outside allowed directories'}, status=403)

        try:
            # Create parent directories if needed
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding='utf-8')
            return web.json_response({
                'status': 'ok',
                'path': file_path,
                'size': len(content.encode('utf-8')),
            })
        except Exception as ex:
            return web.json_response({'error': str(ex)}, status=500)

    # --- API: Regions ---

    # Standard public region ID pattern: xx-yyyy or xx-yyyy-N (e.g. cn-hangzhou, ap-southeast-1)
    _STANDARD_REGION_RE = re.compile(r'^(cn|ap|eu|us|me)-[a-z]+(-\d+)?$')

    async def list_regions(request):
        """GET /api/regions?lang=zh|en - List regions with localized names."""
        lang = request.query.get('lang', 'zh')
        try:
            plugin = StackPlugin(region_id='cn-hangzhou', credential=None)
            regions = await plugin.get_regions(lang=lang)
            # Filter to only standard public regions
            regions = [r for r in regions if _STANDARD_REGION_RE.match(r['id'])]
            return web.json_response({'regions': regions})
        except Exception as ex:
            LOG.warning(f'Failed to fetch regions: {ex}')
            # Fallback with bilingual names
            if lang == 'en':
                fallback = [
                    {'id': 'cn-hangzhou', 'name': 'China East 1 (Hangzhou)'},
                    {'id': 'cn-shanghai', 'name': 'China East 2 (Shanghai)'},
                    {'id': 'cn-beijing', 'name': 'China North 2 (Beijing)'},
                    {'id': 'cn-shenzhen', 'name': 'China South 1 (Shenzhen)'},
                    {'id': 'cn-zhangjiakou', 'name': 'China North 3 (Zhangjiakou)'},
                    {'id': 'cn-huhehaote', 'name': 'China North 5 (Hohhot)'},
                    {'id': 'cn-wulanchabu', 'name': 'China North 6 (Ulanqab)'},
                    {'id': 'cn-chengdu', 'name': 'China Southwest 1 (Chengdu)'},
                    {'id': 'cn-qingdao', 'name': 'China North 1 (Qingdao)'},
                    {'id': 'cn-guangzhou', 'name': 'China South 3 (Guangzhou)'},
                    {'id': 'cn-heyuan', 'name': 'China South 2 (Heyuan)'},
                    {'id': 'cn-nanjing', 'name': 'China East 5 (Nanjing)'},
                    {'id': 'cn-fuzhou', 'name': 'China East 6 (Fuzhou)'},
                    {'id': 'ap-southeast-1', 'name': 'Singapore'},
                    {'id': 'ap-southeast-3', 'name': 'Kuala Lumpur'},
                    {'id': 'ap-southeast-5', 'name': 'Jakarta'},
                    {'id': 'ap-southeast-6', 'name': 'Manila'},
                    {'id': 'ap-southeast-7', 'name': 'Bangkok'},
                    {'id': 'ap-northeast-1', 'name': 'Tokyo'},
                    {'id': 'ap-northeast-2', 'name': 'Seoul'},
                    {'id': 'ap-south-1', 'name': 'Mumbai'},
                    {'id': 'eu-central-1', 'name': 'Frankfurt'},
                    {'id': 'eu-west-1', 'name': 'London'},
                    {'id': 'us-west-1', 'name': 'Silicon Valley'},
                    {'id': 'us-east-1', 'name': 'Virginia'},
                    {'id': 'me-east-1', 'name': 'Dubai'},
                ]
            else:
                fallback = [
                    {'id': 'cn-hangzhou', 'name': '华东1（杭州）'},
                    {'id': 'cn-shanghai', 'name': '华东2（上海）'},
                    {'id': 'cn-beijing', 'name': '华北2（北京）'},
                    {'id': 'cn-shenzhen', 'name': '华南1（深圳）'},
                    {'id': 'cn-zhangjiakou', 'name': '华北3（张家口）'},
                    {'id': 'cn-huhehaote', 'name': '华北5（呼和浩特）'},
                    {'id': 'cn-wulanchabu', 'name': '华北6（乌兰察布）'},
                    {'id': 'cn-chengdu', 'name': '西南1（成都）'},
                    {'id': 'cn-qingdao', 'name': '华北1（青岛）'},
                    {'id': 'cn-guangzhou', 'name': '华南3（广州）'},
                    {'id': 'cn-heyuan', 'name': '华南2（河源）'},
                    {'id': 'cn-nanjing', 'name': '华东5（南京）'},
                    {'id': 'cn-fuzhou', 'name': '华东6（福州）'},
                    {'id': 'ap-southeast-1', 'name': 'Singapore'},
                    {'id': 'ap-southeast-3', 'name': 'Kuala Lumpur'},
                    {'id': 'ap-southeast-5', 'name': 'Jakarta'},
                    {'id': 'ap-southeast-6', 'name': 'Manila'},
                    {'id': 'ap-southeast-7', 'name': 'Bangkok'},
                    {'id': 'ap-northeast-1', 'name': 'Tokyo'},
                    {'id': 'ap-northeast-2', 'name': 'Seoul'},
                    {'id': 'ap-south-1', 'name': 'Mumbai'},
                    {'id': 'eu-central-1', 'name': 'Frankfurt'},
                    {'id': 'eu-west-1', 'name': 'London'},
                    {'id': 'us-west-1', 'name': 'Silicon Valley'},
                    {'id': 'us-east-1', 'name': 'Virginia'},
                    {'id': 'me-east-1', 'name': 'Dubai'},
                ]
            return web.json_response({'regions': fallback, 'fallback': True})

    # --- API: Projects (template + config pairs) ---

    async def list_projects(request):
        """GET /api/projects - List all saved template+config pairs."""
        _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        projects = []
        for f in sorted(_PROJECTS_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                projects.append({
                    'name': data.get('name', f.stem),
                    'created_at': data.get('created_at', ''),
                    'updated_at': data.get('updated_at', ''),
                    'template_preview': (data.get('template', '') or '')[:100],
                    'config_preview': (data.get('config', '') or '')[:100],
                })
            except Exception:
                continue
        return web.json_response({'projects': projects})

    async def get_project(request):
        """GET /api/projects/{name} - Get a specific project."""
        name = request.match_info['name']
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return web.json_response(data)

    async def save_project(request):
        """POST /api/projects - Create or update a project."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        name = (params.get('name') or '').strip()
        if not name:
            return web.json_response({'error': 'Project name is required'}, status=400)

        _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        project_file = _PROJECTS_DIR / f'{name}.json'

        import time
        now = str(time.time())
        if project_file.exists():
            with open(project_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            created_at = existing.get('created_at', now)
        else:
            created_at = now

        data = {
            'name': name,
            'template': params.get('template', ''),
            'config': params.get('config', ''),
            'created_at': created_at,
            'updated_at': now,
        }
        with open(project_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return web.json_response({'status': 'ok', 'name': name})

    async def delete_project(request):
        """DELETE /api/projects/{name} - Delete a project."""
        name = request.match_info['name']
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        project_file.unlink()
        return web.json_response({'status': 'deleted', 'name': name})

    async def get_examples(request):
        """GET /api/projects/examples - Get example template and config."""
        return web.json_response({
            'template': _EXAMPLE_TEMPLATE,
            'config': _EXAMPLE_CONFIG,
        })

    # --- API: Analysis History ---

    async def list_history(request):
        """GET /api/history - List analysis history."""
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        project_name = request.query.get('project_name', '')
        entries = []
        for f in sorted(_HISTORY_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if project_name and data.get('project_name') != project_name:
                    continue
                entries.append(data)
            except Exception:
                continue
        return web.json_response({'history': entries[:50]})

    async def get_history(request):
        """GET /api/history/{id} - Get a specific history entry."""
        entry_id = request.match_info['id']
        history_file = _HISTORY_DIR / f'{entry_id}.json'
        if not history_file.exists():
            return web.json_response({'error': 'History entry not found'}, status=404)
        with open(history_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return web.json_response(data)

    async def delete_history(request):
        """DELETE /api/history/{id} - Delete a history entry."""
        entry_id = request.match_info['id']
        history_file = _HISTORY_DIR / f'{entry_id}.json'
        if not history_file.exists():
            return web.json_response({'error': 'History entry not found'}, status=404)
        history_file.unlink()
        return web.json_response({'status': 'deleted', 'id': entry_id})

    async def cleanup_history(request):
        """POST /api/history/cleanup - Clear all history."""
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in _HISTORY_DIR.glob('*.json'):
            f.unlink()
            count += 1
        return web.json_response({'deleted': count})

    # --- Register routes ---
    app.router.add_get('/api/runs', list_runs)
    app.router.add_post('/api/runs', start_run)
    app.router.add_get('/api/runs/{run_id}', get_run)
    app.router.add_post('/api/runs/{run_id}/cancel', cancel_run)
    app.router.add_post('/api/runs/{run_id}/delete-stacks', delete_run_stacks)
    app.router.add_delete('/api/runs/{run_id}', delete_run)

    app.router.add_post('/api/validate', validate_template)
    app.router.add_post('/api/cost', estimate_cost)
    app.router.add_post('/api/preview', preview_resources)
    app.router.add_post('/api/policy', generate_policy)

    app.router.add_get('/api/reports', list_reports)
    app.router.add_get('/api/reports/{filename}/raw', get_report_raw)
    app.router.add_get('/api/reports/{filename}', get_report_file)
    app.router.add_delete('/api/reports/{filename}', delete_report)
    app.router.add_post('/api/reports/cleanup', cleanup_reports)

    app.router.add_post('/api/upload', upload_template)
    app.router.add_get('/api/templates', list_templates)
    app.router.add_delete('/api/templates/{filename}', delete_saved_file)

    app.router.add_get('/api/settings', get_settings)
    app.router.add_post('/api/settings', save_settings)

    app.router.add_post('/api/config/template-path', update_config_template)

    app.router.add_get('/api/file', read_file)
    app.router.add_post('/api/file', write_file)

    app.router.add_get('/api/regions', list_regions)

    app.router.add_get('/api/projects', list_projects)
    app.router.add_post('/api/projects', save_project)
    app.router.add_get('/api/projects/examples', get_examples)
    app.router.add_get('/api/projects/{name}', get_project)
    app.router.add_delete('/api/projects/{name}', delete_project)

    app.router.add_get('/api/history', list_history)
    app.router.add_post('/api/history/cleanup', cleanup_history)
    app.router.add_get('/api/history/{id}', get_history)
    app.router.add_delete('/api/history/{id}', delete_history)
