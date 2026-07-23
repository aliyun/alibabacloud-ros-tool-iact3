# -*- coding: utf-8 -*-
import asyncio
import contextlib
import io
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from aiohttp import web
from Tea.exceptions import TeaException

from iact3.config import TemplateConfig, BaseConfig, DEFAULT_AUTH_FILE, DEFAULT_CONFIG_FILE, DEFAULT_OUTPUT_DIRECTORY, DEFAULT_PROJECT_ROOT, PROJECT, REGIONS, TEMPLATE_CONFIG, TEMPLATE_BODY, TEMPLATE_LOCATION
from iact3.plugin.ros import StackPlugin
from iact3.testing.ros_stack import StackTest
from iact3.util import yaml as iact3_yaml, CustomSafeLoader, pick_cheapest_instance_type
from iact3.web.runner import capture_iact3_logs, _RUNS_DIR

LOG = logging.getLogger(__name__)

# Unified directory for web-managed files
_UPLOAD_DIR = Path(DEFAULT_PROJECT_ROOT) / '.iact3'
_PROJECTS_DIR = _UPLOAD_DIR / 'projects'
_HISTORY_DIR = _UPLOAD_DIR / 'history'

# Settings file for persistent web configuration
_SETTINGS_FILE = Path('.iact3_web_settings.json')

ALLOWED_TEMPLATE_EXTENSIONS = {'.json', '.yaml', '.yml', '.tf'}

# Project name validation pattern (same as save_project)
_PROJECT_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,254}$')


def _validate_project_name(name):
    """Return True if name is a safe project identifier."""
    return bool(name and _PROJECT_NAME_RE.match(name))


def _is_path_within(path, allowed_roots):
    """Check that *path* (resolved) is inside one of *allowed_roots*.

    Uses Path.relative_to() for strict containment — string prefix
    matching is unsafe (e.g. /home/user/project-evil vs /home/user/project).
    """
    resolved = Path(path).resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _is_file_path_allowed(resolved_path):
    """Check that a resolved file path is within an allowed directory.

    Allowed directories are the project root and the upload directory.
    The user's home directory is NOT allowed — it contains sensitive
    files like ~/.ssh/id_rsa and ~/.aws/credentials.
    """
    allowed_roots = [DEFAULT_PROJECT_ROOT, _UPLOAD_DIR]
    return _is_path_within(resolved_path, allowed_roots)

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

_ECS_INSTANCE_TEMPLATE = """{
  \"ROSTemplateFormatVersion\": \"2015-09-01\",
  \"Parameters\": {
    \"ZoneId\": { \"Type\": \"String\" },
    \"InstanceType\": { \"Type\": \"String\" },
    \"SystemDiskCategory\": { \"Type\": \"String\" },
    \"DataDiskCategory\": { \"Type\": \"String\" },
    \"VpcId\": { \"Type\": \"String\" },
    \"VswitchId\": { \"Type\": \"String\" },
    \"InstanceName\": { \"Type\": \"String\" },
    \"Password\": { \"Type\": \"String\" },
    \"InstanceChargeType\": { \"Type\": \"String\" },
    \"NetworkType\": { \"Type\": \"String\" },
    \"AllocatePublicIP\": { \"Type\": \"String\" },
    \"SecurityGroupId\": { \"Type\": \"String\" },
    \"ImageId\": { \"Type\": \"String\", \"Default\": \"aliyun_3_x64_20G_alibase_\" }
  },
  \"Resources\": {
    \"Server\": {
      \"Type\": \"ALIYUN::ECS::InstanceGroup\",
      \"Properties\": {
        \"ImageId\": { \"Ref\": \"ImageId\" },
        \"MaxAmount\": 1,
        \"VpcId\": { \"Ref\": \"VpcId\" },
        \"VSwitchId\": { \"Ref\": \"VswitchId\" },
        \"InstanceName\": { \"Ref\": \"InstanceName\" },
        \"InstanceType\": { \"Ref\": \"InstanceType\" },
        \"ZoneId\": { \"Ref\": \"ZoneId\" },
        \"SystemDiskCategory\": { \"Ref\": \"SystemDiskCategory\" },
        \"DiskMappings\": [
          { \"Category\": { \"Ref\": \"DataDiskCategory\" }, \"Size\": 40 }
        ],
        \"Password\": { \"Ref\": \"Password\" },
        \"InstanceChargeType\": { \"Ref\": \"InstanceChargeType\" },
        \"NetworkType\": { \"Ref\": \"NetworkType\" },
        \"AllocatePublicIP\": { \"Ref\": \"AllocatePublicIP\" },
        \"SecurityGroupId\": { \"Ref\": \"SecurityGroupId\" }
      }
    }
  }
}
"""

_ECS_INSTANCE_CONFIG = """project:
  name: ecs-instance
tests:
  default:
    regions:
      - cn-hangzhou
    parameters:
      ZoneId: $[iact3-auto]
      InstanceType: $[iact3-auto]
      SystemDiskCategory: cloud_essd
      DataDiskCategory: cloud_essd
      VpcId: $[iact3-auto]
      VswitchId: $[iact3-auto]
      SecurityGroupId: $[iact3-auto]
      InstanceName: iact3-ecs-test
      Password: $[iact3-auto]
      InstanceChargeType: PostPaid
      NetworkType: vpc
      AllocatePublicIP: false
"""

_TERRAFORM_EXAMPLE_FILES = {
    'main.tf': '''resource "alicloud_vpc" "vpc" {
  vpc_name   = "tf-demo-vpc"
  cidr_block = "10.0.0.0/16"
}

resource "alicloud_vswitch" "vsw" {
  vpc_id     = alicloud_vpc.vpc.id
  cidr_block = "10.0.1.0/24"
  zone_id    = "cn-hangzhou-i"
}
''',
}

_TERRAFORM_EXAMPLE_CONFIG = """project:
  name: terraform-vpc
tests:
  default:
    regions:
      - cn-hangzhou
"""

_SAMPLES = {
    'vpc': {
        'name': 'Simple VPC',
        'zh_name': '简单 VPC',
        'template': _EXAMPLE_TEMPLATE,
        'config': _EXAMPLE_CONFIG,
    },
    'ecs-instance': {
        'name': 'ECS Instance Group',
        'zh_name': 'ECS 实例组',
        'template': _ECS_INSTANCE_TEMPLATE,
        'config': _ECS_INSTANCE_CONFIG,
    },
    'terraform-vpc': {
        'name': 'Terraform VPC',
        'zh_name': 'Terraform VPC',
        'template_files': _TERRAFORM_EXAMPLE_FILES,
        'config': _TERRAFORM_EXAMPLE_CONFIG,
    },
}


def _sync_project_name_in_config(config_yaml, project_name):
    """Inject/update project.name in config YAML content."""
    if not config_yaml or not project_name:
        return config_yaml
    lines = config_yaml.split('\n')
    in_project = False
    name_updated = False
    name_inserted = False
    result = []
    name_line = f'  name: {json.dumps(project_name, ensure_ascii=False)}'

    for line in lines:
        trimmed = line.strip()
        if re.match(r'^project\s*:', line):
            in_project = True
            result.append(line)
            continue
        if in_project and trimmed and not line.startswith(' ') and not line.startswith('\t') and trimmed != '---':
            if not name_inserted:
                result.append(name_line)
                name_inserted = True
                name_updated = True
            in_project = False
        if in_project and re.match(r'^\s+name\s*:', line):
            result.append(name_line)
            name_updated = True
            name_inserted = True
            continue
        result.append(line)

    if in_project and not name_inserted:
        result.append(name_line)
        name_updated = True

    if not name_updated:
        if result and result[-1].strip():
            result.append('')
        result.append('project:')
        result.append(name_line)

    return '\n'.join(result)


def _strip_project_name_from_config(config_yaml):
    """Return config YAML with the project.name line removed.

    Used when matching historical runs against a project's current configs,
    so that renaming a project does not break associations based on config content.
    """
    if not config_yaml:
        return config_yaml
    lines = config_yaml.split('\n')
    in_project = False
    result = []
    for line in lines:
        if re.match(r'^project\s*:', line):
            in_project = True
            result.append(line)
            continue
        if in_project:
            trimmed = line.strip()
            if trimmed and not line.startswith(' ') and not line.startswith('\t') and trimmed != '---':
                in_project = False
            elif re.match(r'^\s+name\s*:', line):
                continue
        result.append(line)
    return '\n'.join(result)


def _config_matches_project(raw_config, project_config_set):
    """Check whether a run's raw config matches one of the project's configs,
    ignoring differences in project.name so renames don't break associations."""
    if not raw_config:
        return False
    normalized_run = _strip_project_name_from_config(raw_config)
    for cfg in project_config_set:
        if _strip_project_name_from_config(cfg) == normalized_run:
            return True
    return False


def _sync_project_name_in_runs(old_name, new_name, runner):
    """Update params.project_name in existing run records after a project rename."""
    if not old_name or not new_name or old_name == new_name or not runner:
        return
    updated = 0
    # Update in-memory runs and persist immediately
    try:
        for run in runner._runs.values():
            params = run.params or {}
            if params.get('project_name') == old_name:
                params['project_name'] = new_name
                runner._save_run_to_disk(run)
                updated += 1
    except Exception as ex:
        LOG.warning('Failed to sync project_name in in-memory runs: %s', ex)

    # Also scan disk for any run files not currently loaded
    try:
        if _RUNS_DIR.exists():
            for run_file in _RUNS_DIR.glob('*.json'):
                try:
                    with open(run_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    params = data.get('params') or {}
                    if params.get('project_name') == old_name:
                        params['project_name'] = new_name
                        with open(run_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                        updated += 1
                except Exception as ex:
                    LOG.warning('Failed to update project_name in run file %s: %s', run_file, ex)
    except Exception as ex:
        LOG.warning('Failed to scan runs directory: %s', ex)

    LOG.warning('[save_project] synced project_name in %d run(s) from %s to %s', updated, old_name, new_name)


def _resolve_project_inputs(params):
    """Resolve template/config content from params or saved project.
    Priority: editor content > saved project.
    Returns: (template_content: str|None, template_files: dict|None, config_content: str|None)
    """
    project_name = params.get('project_name')
    template_content = params.get('template_content')
    template_files = params.get('template_files')
    config_content = params.get('config_content')
    has_template = 'template_content' in params
    has_template_files = 'template_files' in params
    has_config = 'config_content' in params

    # Load saved project as fallback (only when editor didn't send both fields)
    saved = None
    if project_name and not (has_template and has_config):
        if not _validate_project_name(project_name):
            LOG.warning(f'Invalid project_name in _resolve_project_inputs: {project_name}')
        else:
            project_file = _PROJECTS_DIR / f'{project_name}.json'
            if project_file.exists():
                try:
                    with open(project_file, 'r', encoding='utf-8') as f:
                        saved = json.load(f)
                except Exception:
                    pass

    # Resolve template files (Terraform directory mode) - takes priority over single content
    if has_template_files:
        resolved_files = template_files
    elif saved and saved.get('template_files'):
        resolved_files = saved['template_files']
    else:
        resolved_files = None

    # Resolve template content (single JSON/YAML template)
    if has_template:
        resolved_tpl = template_content  # may be empty string
    elif resolved_files:
        resolved_tpl = None
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
        '[_resolve_project_inputs] project=%s tpl_len=%d files=%s cfg_len=%d',
        project_name,
        len(resolved_tpl) if resolved_tpl else 0,
        list(resolved_files.keys()) if resolved_files else None,
        len(resolved_cfg) if resolved_cfg else 0,
    )
    return resolved_tpl, resolved_files, resolved_cfg


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
            lines += ['project:', f'  name: {json.dumps(project_name, ensure_ascii=False)}', '']
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


# Regex patterns for parameters that ParamGenerator can auto-resolve.
# When auto-generating or running tests, these parameters are always set to
# $[iact3-auto] so they get properly resolved per region/zone.
# These patterns match region-specific resources whose template defaults
# may be incompatible with the target region, so user values are overwritten.
_AUTO_OVERWRITE_PATTERNS = [
    re.compile(r'(\w*)zone(_|)id(_|)(\d*)', re.I),
    re.compile(r'(\w*)vpc(_|)id(_|)(\d*)', re.I),
    re.compile(r'(\w*)v(_|)switch(_|)id(_|)(\d*)', re.I),
    re.compile(r'(\w*)security(_|)group(_id|id)(_|)(\d*)', re.I),
    re.compile(r'(\w*)instance(_|)type(\w*)', re.I),
    re.compile(r'(\w*)system(_|)disk(_|)(category|type)(\w*)', re.I),
    re.compile(r'(\w*)DBInstanceClass(\w*)', re.I),
]

# Exact parameter names for values that iact3 can safely generate.
# These are only set to $[iact3-auto] when the user has NOT provided a value,
# so explicit user values are preserved.
_AUTO_GENERATE_NAMES = frozenset({
    'Name', 'StackName',
    'Password', 'DBPassword', 'AdminPassword',
    'UUID', 'Uuid',
})

# Sensible defaults for common parameters that cannot be auto-resolved.
# Used when the template has no Default value, so the user gets a working
# starting point instead of an empty string.
_COMMON_DEFAULTS = {
    'ImageId': 'aliyun_3_x64_20G_alibase_',
    'image_id': 'aliyun_3_x64_20G_alibase_',
}


def _get_param_default(param_name, param_def, is_terraform=False):
    """Get a default value for a non-auto parameter.

    Priority: template Default > _COMMON_DEFAULTS > empty string.
    """
    if is_terraform:
        default_val = param_def.get('default') if isinstance(param_def, dict) else None
        if default_val is not None:
            return str(default_val)
    else:
        if isinstance(param_def, dict) and 'Default' in param_def:
            default_val = param_def['Default']
            if default_val is not None:
                return str(default_val)
    # Fall back to common defaults for well-known parameter names
    if param_name in _COMMON_DEFAULTS:
        return _COMMON_DEFAULTS[param_name]
    return ''


def _is_auto_overwrite(name):
    """Check if a parameter should always be overwritten with $[iact3-auto]."""
    return any(p.fullmatch(name) for p in _AUTO_OVERWRITE_PATTERNS)


def _is_auto_generatable(name):
    """Check if a parameter can be auto-generated (but only if not user-supplied)."""
    return name in _AUTO_GENERATE_NAMES


def _is_auto_resolvable(name):
    """Check if a parameter is auto-resolvable (overwrite or generatable)."""
    return _is_auto_overwrite(name) or _is_auto_generatable(name)


def _inject_auto_params(template_content, template_files, config_content):
    """Ensure config has $[iact3-auto] for auto-resolvable parameters.

    Parses the template to discover its Parameters section, then ensures
    that auto-resolvable parameters (InstanceType, SystemDiskCategory,
    ZoneId, VpcId, VSwitchId, SecurityGroupId, etc.) are set to
    $[iact3-auto] in the config, overriding any template Default values
    that may be incompatible with the target region/zone.

    Each test configuration is processed independently so that different
    tests can have different parameter values.

    Returns the updated config_content string.
    """
    import io as _io

    # Parse existing config
    if config_content:
        try:
            config_dict = iact3_yaml.load(_io.StringIO(config_content), Loader=CustomSafeLoader)
        except Exception:
            config_dict = {}
    else:
        config_dict = {}

    # Discover parameters from template
    is_terraform = bool(template_files)
    tpl_params = None  # dict of param_name -> param_def (ROS) or var_name -> var_info (TF)
    if is_terraform:
        tpl_params = _parse_terraform_variables(template_files)
    else:
        tpl_body = template_content
        if tpl_body:
            try:
                tpl_parsed = json.loads(tpl_body) if isinstance(tpl_body, str) else tpl_body
            except (json.JSONDecodeError, TypeError):
                try:
                    tpl_parsed = iact3_yaml.load(
                        _io.StringIO(tpl_body) if isinstance(tpl_body, str) else tpl_body,
                        Loader=CustomSafeLoader,
                    )
                except Exception:
                    tpl_parsed = None
            if isinstance(tpl_parsed, dict):
                tpl_params = tpl_parsed.get('Parameters', {})
                if not isinstance(tpl_params, dict):
                    tpl_params = None

    if tpl_params is None:
        return config_content

    def _process_test_params(existing_params):
        """Process a single test's parameters and return updated dict."""
        if not isinstance(existing_params, dict):
            existing_params = {}

        # Keep only parameters defined in the template
        params = {k: v for k, v in existing_params.items() if k in tpl_params}

        for param_name, param_def in tpl_params.items():
            if _is_auto_overwrite(param_name):
                # Region-specific: always set to $[iact3-auto] (template defaults
                # may be incompatible with the target region/zone)
                params[param_name] = '$[iact3-auto]'
            elif _is_auto_generatable(param_name):
                # Generatable: only set if user has NOT provided a value
                if param_name not in params or not params[param_name]:
                    params[param_name] = '$[iact3-auto]'
            elif param_name not in params:
                # Non-auto parameter: use template Default if available,
                # otherwise use a common default or leave empty.
                params[param_name] = _get_param_default(param_name, param_def, is_terraform)

        return params

    # Update each test independently (don't merge across tests)
    if config_dict and 'tests' in config_dict and isinstance(config_dict['tests'], dict):
        for _test_name, test_cfg in config_dict['tests'].items():
            if isinstance(test_cfg, dict):
                test_cfg['parameters'] = _process_test_params(test_cfg.get('parameters'))
    elif config_dict and 'parameters' in config_dict:
        config_dict['parameters'] = _process_test_params(config_dict.get('parameters'))
    else:
        # No existing config structure — create minimal one
        config_dict = config_dict or {}
        config_dict.setdefault('tests', {}).setdefault('default', {})['parameters'] = _process_test_params({})

    output = _io.StringIO()
    iact3_yaml.dump(config_dict, output)
    return output.getvalue()


def _write_current_files(template_content, config_content, template_files=None, subdir=None):
    """Write content to .iact3/_current/ temp files for tools that require file paths.
    For Terraform directories, template_files is a dict {filename: content} and will be
    written to a dedicated subdirectory so StackTest can use template_location.
    Returns: (template_path: str|None, config_path: str|None, req_id: str|None)
    """
    current_dir = _UPLOAD_DIR / '_current'
    current_dir.mkdir(parents=True, exist_ok=True)
    # Always use a unique subdirectory to avoid collisions between concurrent requests
    req_id = subdir or uuid.uuid4().hex[:12]
    req_dir = current_dir / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    tpl_path = cfg_path = None
    if template_files:
        tf_dir = req_dir
        tf_dir_resolved = tf_dir.resolve()
        for fname, fcontent in template_files.items():
            # Reject absolute paths and path traversal in filenames
            if os.path.isabs(fname) or '..' in Path(fname).parts:
                LOG.warning(f'Skipping template file with unsafe path: {fname}')
                continue
            p = (tf_dir / fname).resolve()
            try:
                p.relative_to(tf_dir_resolved)
            except ValueError:
                LOG.warning(f'Skipping template file outside tf_dir: {fname}')
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(fcontent, encoding='utf-8')
        tpl_path = str(tf_dir.relative_to(DEFAULT_PROJECT_ROOT))
    elif template_content:
        p = req_dir / 'template.yaml'
        p.write_text(template_content, encoding='utf-8')
        tpl_path = str(p.relative_to(DEFAULT_PROJECT_ROOT))
    if config_content:
        p = req_dir / 'config.yml'
        p.write_text(config_content, encoding='utf-8')
        cfg_path = str(p.relative_to(DEFAULT_PROJECT_ROOT))
    return tpl_path, cfg_path, req_id


def _cleanup_current_files(subdir=None):
    """Remove temp files in .iact3/_current/ after one-shot analysis operations."""
    current_dir = _UPLOAD_DIR / '_current'
    if subdir:
        try:
            req_dir = current_dir / subdir
            if req_dir.exists():
                shutil.rmtree(req_dir)
        except Exception:
            pass
    else:
        # Fallback cleanup for legacy fixed-name files
        for fname in ('template.yaml', 'config.yml'):
            try:
                f = current_dir / fname
                if f.exists():
                    f.unlink()
            except Exception:
                pass


def _prepare_template_location(template_files):
    """Write Terraform files to a unique subdirectory and return an absolute path.
    Returns: (template_location: str, tf_subdir: str)
    """
    tf_subdir = f'terraform_{uuid.uuid4().hex[:12]}'
    tpl_path, _, _ = _write_current_files(None, None, template_files=template_files, subdir=tf_subdir)
    return str(Path(DEFAULT_PROJECT_ROOT) / tpl_path), tf_subdir


def _resolve_credential(config_content, template_location=None, template_body=None, regions=None):
    """Build BaseConfig from a temp config file and return the credential to use.
    Falls back to default credential chain (~/.aliyun/config.json) when config_content
    is empty or has schema validation errors (e.g. parameters as a string).
    """
    def _fallback_credential():
        try:
            from iact3.config import Auth
            return Auth()._get_credential()
        except Exception:
            return None

    if not config_content or not config_content.strip():
        return _fallback_credential()
    cfg_subdir = None
    try:
        _, cfg_path, cfg_subdir = _write_current_files(None, config_content)
        if template_location:
            args = {TEMPLATE_CONFIG: {TEMPLATE_LOCATION: template_location}}
        else:
            args = {TEMPLATE_CONFIG: {TEMPLATE_BODY: template_body}}
        if regions:
            # regions can be a list or a string
            if isinstance(regions, list):
                regions_str = ','.join(regions)
            else:
                regions_str = regions
            args[REGIONS] = regions_str.split(',')
        base_config = BaseConfig.create(
            project_config_file=cfg_path or DEFAULT_CONFIG_FILE,
            args={PROJECT: args},
            project_path=DEFAULT_PROJECT_ROOT,
        )
        if base_config.tests:
            return next(iter(base_config.tests.values())).auth.credential
        return base_config.project.auth.credential
    except Exception as ex:
        LOG.debug(f'Config schema validation failed, using fallback credential: {ex}')
        return _fallback_credential()
    finally:
        if cfg_subdir:
            _cleanup_current_files(subdir=cfg_subdir)


def _is_terraform_template_body(template_body):
    """Return True if the rendered template body is a Terraform wrapper."""
    if not template_body:
        return False
    try:
        body = json.loads(template_body)
    except Exception:
        return False
    return body.get('Transform') == 'Aliyun::Terraform-v1.2'


def _config_has_regions(config_content):
    """Return True if config YAML contains at least one non-empty region under tests."""
    if not config_content or not config_content.strip():
        return False
    try:
        parsed = iact3_yaml.safe_load(config_content)
    except Exception:
        return False
    if not isinstance(parsed, dict):
        return False
    tests = parsed.get('tests')
    if not tests or not isinstance(tests, dict):
        return False
    for test_cfg in tests.values():
        if isinstance(test_cfg, dict):
            regions = test_cfg.get('regions') or []
            if isinstance(regions, list) and any(r and str(r).lower() != 'all' for r in regions):
                return True
    return False


def _save_history(project_name, analysis_type, result, error=None, max_entries=50):
    """Save analysis result to history, keeping at most max_entries records."""
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
        # Rolling cleanup: keep only the newest max_entries files
        all_files = sorted(_HISTORY_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_file in all_files[max_entries:]:
            try:
                old_file.unlink()
            except Exception:
                pass
        return entry['id']
    except Exception as ex:
        LOG.warning(f'Failed to save history: {ex}', exc_info=True)
        return None


def _parse_terraform_variables(template_files):
    """Parse `variable` blocks from .tf files.
    Returns: dict of {var_name: {'default': value|None, 'type': type_str|None, 'description': str|None}}
    """
    variables = {}
    if not template_files:
        return variables
    # Regex to find variable block starts
    re_var_start = re.compile(r'^\s*variable\s+"([^"]+)"\s*\{', re.MULTILINE)
    for fname, content in template_files.items():
        if not fname.endswith('.tf') or not content:
            continue
        for m in re_var_start.finditer(content):
            var_name = m.group(1)
            # Find matching closing brace, skipping braces inside strings and comments
            start = m.end()
            depth = 1
            pos = start
            in_string = False
            in_line_comment = False
            while pos < len(content) and depth > 0:
                ch = content[pos]
                if in_line_comment:
                    if ch == '\n':
                        in_line_comment = False
                elif in_string:
                    if ch == '\\':
                        pos += 1  # skip escaped char
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == '#' or (ch == '/' and pos + 1 < len(content) and content[pos + 1] == '/'):
                        in_line_comment = True
                    elif ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                pos += 1
            if depth != 0:
                continue
            block = content[start:pos - 1]
            var_info = {'default': None, 'type': None, 'description': None}
            # Parse default value
            m_default = re.search(r'^\s*default\s*=\s*(.+)', block, re.MULTILINE)
            if m_default:
                raw = m_default.group(1).strip()
                # Handle quoted strings
                if raw.startswith('"') and raw.endswith('"'):
                    var_info['default'] = raw[1:-1]
                elif raw.startswith('[') or raw.startswith('{'):
                    # Complex types - keep as string representation
                    var_info['default'] = raw
                elif raw.lower() == 'true':
                    var_info['default'] = 'true'
                elif raw.lower() == 'false':
                    var_info['default'] = 'false'
                elif raw.lower() == 'null':
                    var_info['default'] = None
                else:
                    var_info['default'] = raw
            # Parse type
            m_type = re.search(r'^\s*type\s*=\s*(.+)', block, re.MULTILINE)
            if m_type:
                var_info['type'] = m_type.group(1).strip()
            # Parse description
            m_desc = re.search(r'^\s*description\s*=\s*"([^"]*)"', block, re.MULTILINE)
            if m_desc:
                var_info['description'] = m_desc.group(1)
            variables[var_name] = var_info
    return variables


async def _resolve_terraform_params(tests_params, region, credential, multi_region=False):
    """Resolve $[iact3-auto] placeholders for Terraform variables using name-based matching.

    ParamGenerator is ROS-specific (relies on AssociationProperty, ROS API constraints),
    so this lightweight resolver uses the same regex patterns to resolve common
    infrastructure parameters (VPC, VSwitch, Zone, SecurityGroup, etc.) for Terraform.

    When multi_region=True, region-specific params (VPC, VSwitch, Zone, SG, InstanceType,
    SystemDisk) are left as $[iact3-auto] for runtime per-region resolution.
    Only non-region params (password, common_name, uuid) are resolved.
    """
    from iact3.generate_params import ParamGenerator
    from iact3.plugin.vpc import VpcPlugin
    from iact3.plugin.ecs import EcsPlugin

    RE_V_AUTO = ParamGenerator.RE_V_AUTO
    # Name patterns for ECS-specific parameters that ROS resolves via AssociationProperty
    RE_K_INSTANCE_TYPE = re.compile(r'(\w*)instance(_|)type(_|)(\w*)', re.I)
    RE_K_SYSTEM_DISK = re.compile(r'(\w*)system(_|)disk(_|)category(\w*)', re.I)

    resolved = dict(tests_params)
    vpc_id = None
    vsw_id = None
    zone_id = None

    if not multi_region:
        # First pass: resolve VPC/VSwitch (other params like SG may depend on these)
        for key, val in resolved.items():
            if not isinstance(val, str) or not RE_V_AUTO.fullmatch(val):
                continue
            if ParamGenerator.RE_K_VPC_ID.fullmatch(key) or ParamGenerator.RE_K_VSW_ID.fullmatch(key):
                if vpc_id is None:
                    try:
                        vpc_plugin = VpcPlugin(region, credential=credential)
                        vsw = await vpc_plugin.get_one_vswitch()
                        if vsw:
                            vpc_id = vsw.get('VpcId')
                            vsw_id = vsw.get('VSwitchId')
                    except Exception as ex:
                        LOG.warning(f'Failed to resolve VPC/VSwitch for Terraform: {ex}')
                if ParamGenerator.RE_K_VPC_ID.fullmatch(key) and vpc_id:
                    resolved[key] = vpc_id
                elif ParamGenerator.RE_K_VSW_ID.fullmatch(key) and vsw_id:
                    resolved[key] = vsw_id

    # Second pass: resolve Zone, SecurityGroup, Name, Password, UUID
    for key, val in resolved.items():
        if not isinstance(val, str) or not RE_V_AUTO.fullmatch(val):
            continue
        if multi_region and ParamGenerator.RE_K_ZONE_ID.fullmatch(key):
            continue  # skip region-specific in multi-region mode
        elif ParamGenerator.RE_K_ZONE_ID.fullmatch(key):
            try:
                ecs_plugin = EcsPlugin(region, credential=credential)
                zones = await ecs_plugin.describe_zones()
                if zones:
                    resolved[key] = zones[0]
                    zone_id = zones[0]
            except Exception:
                pass
        elif multi_region and ParamGenerator.RE_K_SECURITY_GROUP.fullmatch(key):
            continue  # skip region-specific in multi-region mode
        elif ParamGenerator.RE_K_SECURITY_GROUP.fullmatch(key):
            if vpc_id:
                try:
                    ecs_plugin = EcsPlugin(region, credential=credential)
                    sg = await ecs_plugin.get_security_group(vpc_id=vpc_id)
                    if sg:
                        resolved[key] = sg['SecurityGroupId']
                except Exception:
                    pass
        elif ParamGenerator.RE_K_COMMON_NAME.fullmatch(key):
            resolved[key] = f'iact3-{uuid.uuid4().hex}'[:50]
        elif ParamGenerator.RE_K_PASSWORD.fullmatch(key):
            import random as _random
            import string as _string
            chars = []
            for s in (_string.ascii_lowercase, '!@#$', _string.digits, _string.ascii_uppercase):
                chars.extend(_random.sample(s, 4))
            resolved[key] = ''.join(chars)
        elif ParamGenerator.RE_K_UUID.fullmatch(key):
            resolved[key] = str(uuid.uuid1())

    if not multi_region:
        # Third pass: resolve ECS-specific params with disk-aware logic.
        # If both InstanceType and SystemDiskCategory exist, query InstanceType
        # with each disk category filter (cloud_essd → cloud_ssd → cloud_efficiency
        # → cloud_auto) and set both values simultaneously to ensure compatibility.
        SAFE_DISK_CATEGORIES = ('cloud_essd', 'cloud_ssd', 'cloud_efficiency', 'cloud_auto')
        it_key = next((k for k in resolved if RE_K_INSTANCE_TYPE.fullmatch(k)
                       and isinstance(resolved[k], str) and RE_V_AUTO.fullmatch(resolved[k])), None)
        sd_key = next((k for k in resolved if RE_K_SYSTEM_DISK.fullmatch(k)
                       and isinstance(resolved[k], str) and RE_V_AUTO.fullmatch(resolved[k])), None)
        if it_key:
            try:
                ecs_plugin = EcsPlugin(region, credential=credential)
                resolved_disk = None
                if sd_key:
                    # Query with each disk category filter in priority order
                    for disk_cat in SAFE_DISK_CATEGORIES:
                        types = await ecs_plugin.describe_available_instance_types(
                            zone_id=zone_id, instance_charge_type='PostPaid',
                            system_disk_category=disk_cat
                        )
                        if types:
                            resolved[it_key] = pick_cheapest_instance_type(types)
                            resolved_disk = disk_cat
                            break
                if it_key not in resolved or RE_V_AUTO.fullmatch(str(resolved.get(it_key, ''))):
                    # No disk param or all disk filters returned empty — query without filter
                    types = await ecs_plugin.describe_available_instance_types(
                        zone_id=zone_id, instance_charge_type='PostPaid'
                    )
                    if types:
                        resolved[it_key] = pick_cheapest_instance_type(types)
            except Exception:
                pass
            if sd_key and resolved_disk:
                resolved[sd_key] = resolved_disk
            elif sd_key:
                resolved[sd_key] = 'cloud_essd'

    if not multi_region:
        # Final pass: replace remaining $[iact3-auto] with empty string
        unresolved = []
        for key, val in resolved.items():
            if isinstance(val, str) and RE_V_AUTO.fullmatch(val):
                resolved[key] = ''
                unresolved.append(key)
        if unresolved:
            LOG.info(f'Terraform variables not auto-resolved (set to empty): {unresolved}')
    else:
        # In multi-region mode, keep $[iact3-auto] for runtime per-region resolution
        unresolved = [k for k, v in resolved.items() if isinstance(v, str) and RE_V_AUTO.fullmatch(v)]
        if unresolved:
            LOG.info(f'Terraform variables kept as $[iact3-auto] for multi-region resolution: {unresolved}')

    return resolved


def _resolve_non_region_params(tests_params):
    """Resolve only non-region-specific parameters for multi-region mode.

    Region-specific params (VPC, VSwitch, Zone, SG, InstanceType, SystemDisk) are
    reset to $[iact3-auto] for runtime per-region resolution, even if they currently
    have concrete values from a previous single-region generation.
    Non-region params (password, common_name, uuid) are resolved to concrete values.
    """
    from iact3.generate_params import ParamGenerator
    import re as _re
    RE_V_AUTO = ParamGenerator.RE_V_AUTO
    # ECS-specific patterns (same as _resolve_terraform_params)
    RE_K_INSTANCE_TYPE = _re.compile(r'(\w*)instance(_|)type(_|)(\w*)', _re.I)
    RE_K_SYSTEM_DISK = _re.compile(r'(\w*)system(_|)disk(_|)category(\w*)', _re.I)

    resolved = dict(tests_params)
    for key, val in resolved.items():
        # Reset region-specific params to $[iact3-auto] (even if they have concrete values)
        if (ParamGenerator.RE_K_VPC_ID.fullmatch(key)
                or ParamGenerator.RE_K_VSW_ID.fullmatch(key)
                or ParamGenerator.RE_K_ZONE_ID.fullmatch(key)
                or ParamGenerator.RE_K_SECURITY_GROUP.fullmatch(key)
                or RE_K_INSTANCE_TYPE.fullmatch(key)
                or RE_K_SYSTEM_DISK.fullmatch(key)):
            resolved[key] = '$[iact3-auto]'
            continue
        # Resolve non-region $[iact3-auto] params to concrete values
        if not isinstance(val, str) or not RE_V_AUTO.fullmatch(val):
            continue
        if ParamGenerator.RE_K_COMMON_NAME.fullmatch(key):
            resolved[key] = f'iact3-{uuid.uuid4().hex}'[:50]
        elif ParamGenerator.RE_K_PASSWORD.fullmatch(key):
            import random as _random
            import string as _string
            chars = []
            for s in (_string.ascii_lowercase, '!@#$', _string.digits, _string.ascii_uppercase):
                chars.extend(_random.sample(s, 4))
            resolved[key] = ''.join(chars)
        elif ParamGenerator.RE_K_UUID.fullmatch(key):
            resolved[key] = str(uuid.uuid1())
    return resolved


def _cleanup_stale_current_files():
    """Remove all stale temp files from .iact3/_current/ left by previous sessions.

    Called once on server startup to ensure no orphaned terraform directories
    or temp config files remain from crashed/restarted server sessions.
    """
    current_dir = _UPLOAD_DIR / '_current'
    if not current_dir.exists():
        return
    cleaned = 0
    # Remove all stale subdirectories (terraform_* and unique uuid hex dirs)
    for child in current_dir.iterdir():
        if child.is_dir():
            try:
                shutil.rmtree(child)
                cleaned += 1
            except Exception as ex:
                LOG.warning(f'Failed to clean stale dir {child}: {ex}')
    # Remove stale temp files (config_preview.yml is from old code, no longer used)
    for fname in ('template.yaml', 'config.yml', 'config_preview.yml'):
        f = current_dir / fname
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass
    if cleaned:
        LOG.info(f'Cleaned {cleaned} stale temp directories from _current/')


async def _poll_stack_deletion(runner, run_id: str, region_groups: dict, credential):
    """Poll ROS for stack deletion status until all reach a terminal state."""
    from iact3.plugin.ros import StackPlugin

    MAX_POLLS = 30  # 30 × 10s = 5 min max
    for _ in range(MAX_POLLS):
        await asyncio.sleep(10)
        all_done = True
        run = runner.get_run_raw(run_id)
        if not run:
            return
        for region, stack_ids in region_groups.items():
            plugin = StackPlugin(region_id=region, credential=credential)
            for stack_id in stack_ids:
                try:
                    info = await plugin.get_stack(stack_id)
                    if info is None:
                        # get_stack returns None for StackNotFound —
                        # the stack has been fully deleted by ROS.
                        status = 'DELETE_COMPLETE'
                    else:
                        status = info.get('Status', 'UNKNOWN')
                except Exception as ex:
                    # Credential errors, timeouts, or ROS service errors
                    # do NOT mean the stack is deleted.  Keep the current
                    # status and retry on the next poll.
                    LOG.warning(f'Error polling stack {stack_id} in {region}: {ex}')
                    status = 'DELETE_IN_PROGRESS'
                for s in run.stacks:
                    if s.get('stack_id') == stack_id:
                        if status in ('DELETE_COMPLETE', 'DELETE_FAILED'):
                            s['status'] = status
                        else:
                            all_done = False
        runner._save_run_to_disk(run)
        if all_done:
            break


def setup_routes(app: web.Application):
    """Register all API routes."""
    # Clean up stale temp files from previous sessions
    _cleanup_stale_current_files()

    runner = app['runner']

    # --- API: Test Runs ---

    async def list_runs(request):
        """GET /api/runs - List test runs.

        Query params:
          - search: filter by run name (case-insensitive)
          - status: filter by run status (case-insensitive)
          - page: 1-based page number
          - per_page: items per page (default 20, max 100)
        """
        search = request.query.get('search', '').strip().lower()
        status = request.query.get('status', '').strip().lower()
        try:
            page = max(1, int(request.query.get('page', 1)))
        except ValueError:
            page = 1
        try:
            per_page = min(100, max(1, int(request.query.get('per_page', 20))))
        except ValueError:
            per_page = 20

        runs = runner.get_all_runs()
        if search:
            runs = [r for r in runs if search in (r.get('name') or '').lower()]
        if status:
            runs = [r for r in runs if (r.get('status') or '').lower() == status]
        total = len(runs)
        start = (page - 1) * per_page
        end = start + per_page
        return web.json_response({
            'runs': runs[start:end],
            'total': total,
            'page': page,
            'per_page': per_page,
        })

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
        template_content, template_files, config_content = _resolve_project_inputs(params)
        # Ensure the config has a `tests:` section so StackTest.from_file
        # creates actual test cases. Inject one using the provided regions when absent.
        regions_str = params.get('regions') or ''
        project_name_for_cfg = params.get('project_name') or ''
        config_content = _ensure_tests_section(config_content, regions_str, project_name_for_cfg)
        # Persist original editor contents for the run detail page BEFORE
        # _inject_auto_params converts them to $[iact3-auto].  The detail
        # page should show the actual parameter values the user sees, not
        # the internal $[iact3-auto] placeholders.
        if template_content is not None:
            params['raw_template_content'] = template_content
        if template_files:
            params['raw_template_files'] = template_files
        if config_content is not None:
            params['raw_config_content'] = config_content
        # Inject $[iact3-auto] for auto-resolvable parameters (InstanceType,
        # SystemDiskCategory, ZoneId, VpcId, etc.) so they get properly resolved
        # per region/zone at runtime, overriding any template Default values
        # that may be incompatible with the target region.
        config_content = _inject_auto_params(template_content, template_files, config_content)
        # Use a unique subdirectory for this run so concurrent runs don't collide
        run_id = uuid.uuid4().hex[:12]
        tpl_path, cfg_path, _ = _write_current_files(
            template_content, config_content, template_files=template_files, subdir=f'terraform_{run_id}'
        )
        if tpl_path:
            params['template'] = tpl_path
        if cfg_path:
            params['config_file'] = cfg_path

        # For Terraform directories, StackTest must use template_location, not template_body
        if template_files:
            params.pop('template_content', None)
        elif template_content:
            params['template_content'] = template_content

        # Use a per-run output directory so reports don't overwrite each other
        params['output_directory'] = f'{DEFAULT_OUTPUT_DIRECTORY}/runs/{run_id}'
        params['name'] = params.get('name', f'test-{run_id}')
        Path(params['output_directory']).mkdir(parents=True, exist_ok=True)

        try:
            run = await runner.start_test_run(params, run_id=run_id)
            return web.json_response(run.to_dict(), status=201)
        except Exception as ex:
            LOG.error(f'Failed to start test run: {ex}', exc_info=True)
            return web.json_response({'error': str(ex)}, status=500)

    async def get_run_logs(request):
        """GET /api/runs/{run_id}/logs - Get raw CLI logs for a run."""
        run_id = request.match_info['run_id']
        logs = runner.get_run_logs(run_id)
        return web.Response(text=logs, content_type='text/plain', charset='utf-8')

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

    async def batch_delete_runs(request):
        """POST /api/runs/batch-delete - Delete multiple test runs."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        ids = params.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return web.json_response({'error': 'ids list is required'}, status=400)
        deleted = []
        failed = []
        for run_id in ids:
            try:
                if runner.delete_run(run_id):
                    deleted.append(run_id)
                else:
                    failed.append({'id': run_id, 'reason': 'cannot delete'})
            except Exception as ex:
                failed.append({'id': run_id, 'reason': str(ex)})
        return web.json_response({'deleted': deleted, 'failed': failed})

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

            # Verify the current credential matches the one used to create the
            # run's stacks.  This prevents accidental cross-account deletion when
            # the CLI profile has been switched since the run was created.
            current_ak = getattr(credential, 'access_key_id', '') or ''
            current_key_id = current_ak[-4:] if len(current_ak) >= 4 else current_ak
            if run.credential_key_id and run.credential_key_id != current_key_id:
                return web.json_response({
                    'error': (
                        f'Credential mismatch: run was created with access key '
                        f'ending in {run.credential_key_id!r}, but the current '
                        f'credential ends in {current_key_id!r}. Switch to the '
                        f'original profile before deleting stacks.'
                    ),
                    'code': 'CREDENTIAL_MISMATCH',
                }, status=403)

            results = []
            errors = []

            # Group by region to minimize plugin creation
            region_groups = {}
            for s in stacks_to_delete:
                region = s.get('region')
                if region:
                    region_groups.setdefault(region, []).append(s['stack_id'])

            log_path = run.log_path if run else None
            with capture_iact3_logs(log_path) if log_path else contextlib.nullcontext():
                LOG.info(f'Starting manual stack deletion for run {run_id}, {len(stacks_to_delete)} stack(s)')
                for region, stack_ids in region_groups.items():
                    plugin = StackPlugin(region_id=region, credential=credential)
                    for stack_id in stack_ids:
                        try:
                            LOG.info(f'Deleting stack {stack_id} in region {region}')
                            await plugin.delete_stack(stack_id)
                            # Record DELETE_IN_PROGRESS — ROS needs time to process.
                            # A background task will poll for the final status.
                            for s in run.stacks:
                                if s.get('stack_id') == stack_id:
                                    s['status'] = 'DELETE_IN_PROGRESS'
                            results.append({'stack_id': stack_id, 'region': region, 'status': 'deleted'})
                            LOG.info(f'Successfully deleted stack {stack_id} in region {region}')
                        except Exception as ex:
                            LOG.error(f'Failed to delete stack {stack_id} in region {region}: {ex}')
                            errors.append({'stack_id': stack_id, 'region': region, 'error': str(ex)})
                LOG.info(f'Finished manual stack deletion for run {run_id}: {len(results)} succeeded, {len(errors)} failed')

            # Persist updated stack statuses
            runner._save_run_to_disk(run)

            # Launch a background task to poll for final deletion status
            if results:
                asyncio.create_task(
                    _poll_stack_deletion(runner, run_id, region_groups, credential)
                )

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
    
        template_content, template_files, config_content = _resolve_project_inputs(params)
        regions = params.get('regions')
        template_args = {}  # Initialize for error logging
        tf_subdir = None

        LOG.warning('[validate] RAW params keys=%s project=%s tpl_content_len=%d files=%s cfg_content_len=%d',
            list(params.keys()),
            params.get('project_name'),
            len(params.get('template_content', '') or ''),
            list(params.get('template_files', {}).keys()) if params.get('template_files') else None,
            len(params.get('config_content', '') or ''),
        )
        LOG.warning('[validate] RESOLVED tpl_len=%d files=%s cfg_len=%d',
            len(template_content) if template_content else 0,
            list(template_files.keys()) if template_files else None,
            len(config_content) if config_content else 0,
        )

        if not template_content and not template_files:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'result': 'invalid',
                 'error': f'模板内容为空，无法校验。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )

        log_path = Path(DEFAULT_OUTPUT_DIRECTORY) / 'validate.log'
        if log_path.exists():
            log_path.unlink()
        try:
            with capture_iact3_logs(log_path):
                if template_files:
                    template_location, tf_subdir = _prepare_template_location(template_files)
                    template_config = TemplateConfig(template_location=template_location)
                    template_args = template_config.generate_template_args()
                    credential = _resolve_credential(config_content, template_location=template_location, regions=regions)
                else:
                    template_config = TemplateConfig(template_body=template_content)
                    template_args = template_config.generate_template_args()
                    credential = _resolve_credential(config_content, template_body=template_content, regions=regions)

                LOG.warning('[validate] tc=%s ta_keys=%s',
                    template_config, list(template_args.keys()))
                plugin = StackPlugin(region_id=None, credential=credential)

                result = await plugin.validate_template(**template_args)
                _save_history(params.get('project_name'), 'validate', {'result': 'valid', 'details': result})
            logs = log_path.read_text(encoding='utf-8') if log_path.exists() else ''
            return web.json_response({'result': 'valid', 'details': result, 'logs': logs})
        except Exception as ex:
            import traceback
            tpl_body = template_args.get('template_body', '')
            LOG.error('[validate] FAILED. template_body len=%d, error_type=%s error=%s\nTraceback:\n%s',
                len(tpl_body), type(ex).__name__, ex, traceback.format_exc())
            _save_history(params.get('project_name'), 'validate', None, error=str(ex))
            err_msg = str(ex) or f'{type(ex).__name__}: (no message)'
            logs = log_path.read_text(encoding='utf-8') if log_path.exists() else ''
            return web.json_response({'result': 'invalid', 'error': err_msg, 'logs': logs}, status=400)
        finally:
            _cleanup_current_files(subdir=tf_subdir)

    # --- API: Cost ---

    async def estimate_cost(request):
        """POST /api/cost - Estimate template cost."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
    
        template_content, template_files, config_content = _resolve_project_inputs(params)
        if not template_content and not template_files:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'error': f'模板内容为空，无法估算费用。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )

        regions_param = (params.get('regions') or '').strip()
        if not regions_param and not _config_has_regions(config_content):
            return web.json_response(
                {'error': '请先选择地域，或在配置文件的 tests.<name>.regions 中填写地域，再进行费用估算。'},
                status=400
            )

        config_content = _ensure_tests_section(
            config_content or '', regions_param, params.get('project_name') or 'iact3-project'
        )

        tf_subdir = None
        cfg_subdir = None
        log_path = Path(DEFAULT_OUTPUT_DIRECTORY) / 'cost.log'
        # Ensure each cost estimate only returns logs for this run.
        if log_path.exists():
            log_path.unlink()
        try:
            with capture_iact3_logs(log_path):
                if template_files:
                    template_location, tf_subdir = _prepare_template_location(template_files)
                    _, cfg_path, cfg_subdir = _write_current_files(None, config_content)
                    test = await StackTest.from_file(
                        template=template_location,
                        project_config_file=cfg_path,
                        regions=regions_param or None,
                    )
                else:
                    _, cfg_path, cfg_subdir = _write_current_files(None, config_content)
                    test = await StackTest.from_file(
                        template=None,
                        project_config_file=cfg_path,
                        regions=regions_param or None,
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
            logs = log_path.read_text(encoding='utf-8') if log_path.exists() else ''
            return web.json_response({'prices': prices, 'logs': logs})
        except TeaException as ex:
            _save_history(params.get('project_name'), 'cost', None, error=_format_tea_exception(ex))
            logs = log_path.read_text(encoding='utf-8') if log_path.exists() else ''
            return web.json_response({'error': _format_tea_exception(ex), 'logs': logs}, status=400)
        except Exception as ex:
            _save_history(params.get('project_name'), 'cost', None, error=str(ex))
            logs = log_path.read_text(encoding='utf-8') if log_path.exists() else ''
            return web.json_response({'error': str(ex), 'logs': logs}, status=500)
        finally:
            _cleanup_current_files(subdir=tf_subdir)
            _cleanup_current_files(subdir=cfg_subdir)

    # --- API: Preview ---

    async def preview_resources(request):
        """POST /api/preview - Preview template resources."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
    
        template_content, template_files, config_content = _resolve_project_inputs(params)
        if not template_content and not template_files:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'error': f'模板内容为空，无法预览资源。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )

        regions_param = (params.get('regions') or '').strip()
        if not regions_param and not _config_has_regions(config_content):
            return web.json_response(
                {'error': '请先选择地域，或在配置文件的 tests.<name>.regions 中填写地域，再进行资源预览。'},
                status=400
            )

        config_content = _ensure_tests_section(
            config_content or '', regions_param, params.get('project_name') or 'iact3-project'
        )

        tf_subdir = None
        cfg_subdir = None
        try:
            if template_files:
                template_location, tf_subdir = _prepare_template_location(template_files)
                _, cfg_path, cfg_subdir = _write_current_files(None, config_content)
                test = await StackTest.from_file(
                    template=template_location,
                    project_config_file=cfg_path,
                    regions=regions_param or None,
                )
            else:
                _, cfg_path, cfg_subdir = _write_current_files(None, config_content)
                test = await StackTest.from_file(
                    template=None,
                    project_config_file=cfg_path,
                    regions=regions_param or None,
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
        finally:
            _cleanup_current_files(subdir=tf_subdir)
            _cleanup_current_files(subdir=cfg_subdir)

    def _append_log(log_path: Path, level: str, message: str):
        """Append a single line to the log file in the same format used by capture_iact3_logs.

        This bypasses the logging subsystem entirely so policy logs are always written
        regardless of the current logger level or handler state.
        """
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'{timestamp} [{level:7s}] : {message}\n')

    # --- API: Policy ---

    async def generate_policy(request):
        """POST /api/policy - Generate template policy."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
    
        template_content, template_files, config_content = _resolve_project_inputs(params)
        regions = params.get('regions')
        if not template_content and not template_files:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'error': f'模板内容为空，无法生成策略。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )

        tf_subdir = None
        policy = None
        log_path = Path(DEFAULT_OUTPUT_DIRECTORY) / 'policy.log'
        if log_path.exists():
            log_path.unlink()
        try:
            with capture_iact3_logs(log_path):
                _append_log(log_path, 'INFO', 'Start generating template policy.')
                try:
                    if template_files:
                        template_location, tf_subdir = _prepare_template_location(template_files)
                        template_config = TemplateConfig(template_location=template_location)
                        template_args = template_config.generate_template_args()
                        credential = _resolve_credential(config_content, template_location=template_location, regions=regions)
                    else:
                        template_config = TemplateConfig(template_body=template_content)
                        template_args = template_config.generate_template_args()
                        credential = _resolve_credential(config_content, template_body=template_content, regions=regions)

                    plugin = StackPlugin(region_id=None, credential=credential)
                    policy = await plugin.generate_template_policy(**template_args)
                    _save_history(params.get('project_name'), 'policy', {'policy': policy})
                    _append_log(log_path, 'INFO', 'Template policy generated successfully.')
                except Exception as ex:
                    _save_history(params.get('project_name'), 'policy', None, error=str(ex))
                    _append_log(log_path, 'ERROR', f'Failed to generate template policy: {ex}')
                    raise
            logs = log_path.read_text(encoding='utf-8') if log_path.exists() else ''
            return web.json_response({'policy': policy, 'logs': logs})
        except Exception as ex:
            logs = log_path.read_text(encoding='utf-8') if log_path.exists() else ''
            return web.json_response({'error': str(ex), 'logs': logs}, status=500)
        finally:
            _cleanup_current_files(subdir=tf_subdir)

    # --- API: Generate Parameters ---

    async def generate_params(request):
        """POST /api/generate-params - Auto-generate parameters from template."""
        import io
        import logging as _logging
        from iact3.generate_params import ParamGenerator
        from iact3.config import TestConfig, Auth
        
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        
        template_content, template_files, config_content = _resolve_project_inputs(params)
        regions_raw = params.get('regions') or ''
        if isinstance(regions_raw, list):
            region_list = [r.strip() for r in regions_raw if r and str(r).strip()]
        else:
            region_list = [r.strip() for r in str(regions_raw).split(',') if r.strip()]
        region = region_list[0] if region_list else 'cn-hangzhou'
        is_multi_region = len(region_list) > 1
        
        if not template_content and not template_files:
            project_name = params.get('project_name', '')
            hint = f'项目「{project_name}」中没有保存模板内容。' if project_name else ''
            return web.json_response(
                {'error': f'模板内容为空，无法生成参数。{hint}请在"模板"编辑器中粘贴或上传模板文件。'},
                status=400
            )
        
        tf_subdir = None
        template_location = None
        try:
            if template_files:
                template_location, tf_subdir = _prepare_template_location(template_files)
                template_config = TemplateConfig(template_location=template_location)
                template_args = template_config.generate_template_args()
            else:
                template_config = TemplateConfig(template_body=template_content)
                template_args = template_config.generate_template_args()
            # Credential is needed for both ROS and Terraform parameter resolution
            credential = _resolve_credential(
                config_content,
                template_location=template_location,
                template_body=template_content if not template_files else None,
                regions=regions_raw,
            )
            
            # Parse existing config content to get parameters
            if config_content:
                try:
                    config_dict = iact3_yaml.load(io.StringIO(config_content), Loader=CustomSafeLoader)
                except Exception:
                    config_dict = {}
            else:
                config_dict = {}
            
            # Extract parameters from tests section (merge all tests' parameters)
            tests_params = {}
            if config_dict and 'tests' in config_dict and isinstance(config_dict['tests'], dict):
                for _test_name, test_cfg in config_dict['tests'].items():
                    if isinstance(test_cfg, dict) and 'parameters' in test_cfg:
                        existing_params = test_cfg['parameters']
                        if isinstance(existing_params, dict):
                            tests_params.update(existing_params)
            elif config_dict and 'parameters' in config_dict:
                existing_params = config_dict['parameters']
                if isinstance(existing_params, dict):
                    tests_params = existing_params
            
            # ── Discover parameters from template ──
            # ParamGenerator only resolves $[iact3-auto] placeholders for
            # parameters that already exist in the config.  When the user
            # changes templates without updating the config editor, the
            # output stays the same regardless of the template.
            # Fix: parse the template to extract its Parameters section,
            # then auto-add any missing parameters with $[iact3-auto].
            is_terraform = bool(template_files)
            tf_variables = {}

            if is_terraform:
                # Terraform: parse `variable` blocks from .tf files
                tf_variables = _parse_terraform_variables(template_files)
                if tf_variables:
                    # Remove config parameters not defined as Terraform variables
                    tests_params = {
                        k: v for k, v in tests_params.items()
                        if k in tf_variables
                    }
                    # Auto-add missing Terraform variables
                    for var_name, var_info in tf_variables.items():
                        if var_name not in tests_params:
                            if var_info.get('default') is not None:
                                tests_params[var_name] = str(var_info['default'])
                            elif _is_auto_resolvable(var_name):
                                tests_params[var_name] = '$[iact3-auto]'
                            else:
                                tests_params[var_name] = _get_param_default(var_name, var_info, is_terraform=True)
            else:
                tpl_body = template_args.get('template_body')
                if tpl_body:
                    try:
                        tpl_parsed = json.loads(tpl_body) if isinstance(tpl_body, str) else tpl_body
                    except (json.JSONDecodeError, TypeError):
                        try:
                            tpl_parsed = iact3_yaml.load(
                                io.StringIO(tpl_body) if isinstance(tpl_body, str) else tpl_body,
                                Loader=CustomSafeLoader,
                            )
                        except Exception:
                            tpl_parsed = None
                    if isinstance(tpl_parsed, dict):
                        tpl_params = tpl_parsed.get('Parameters', {})
                        if isinstance(tpl_params, dict):
                            # Remove config parameters NOT defined in the template.
                            # Otherwise ROS API returns UnknownUserParameter (400)
                            # when stale params from a previous template are sent.
                            tests_params = {
                                k: v for k, v in tests_params.items()
                                if k in tpl_params
                            }
                            # Auto-add template parameters missing from config.
                            # For region-specific parameters (ZoneId, VpcId, VSwitchId,
                            # SecurityGroupId, InstanceType, SystemDiskCategory, DBInstanceClass),
                            # always use $[iact3-auto] so they get resolved per region.
                            # For generatable parameters (Name, Password, UUID), only use
                            # $[iact3-auto] if the user has not provided a value.
                            # For other parameters, use the template Default if available.
                            for param_name, param_def in tpl_params.items():
                                if _is_auto_overwrite(param_name):
                                    tests_params[param_name] = '$[iact3-auto]'
                                elif _is_auto_generatable(param_name):
                                    if param_name not in tests_params or not tests_params[param_name]:
                                        tests_params[param_name] = '$[iact3-auto]'
                                elif param_name not in tests_params:
                                    tests_params[param_name] = _get_param_default(param_name, param_def)
            
            # For Terraform, ParamGenerator (ROS-specific) cannot be used directly.
            # Use name-based resolution for common infrastructure parameters.
            if is_terraform:
                if credential is None:
                    return web.json_response(
                        {'error': '未找到阿里云凭证，无法自动生成参数。请在配置中设置 auth 部分，或先在 ~/.aliyun/config.json 中配置阿里云凭证。'},
                        status=400
                    )
                if is_multi_region:
                    # Reset region-specific params to $[iact3-auto] before resolving
                    tests_params = _resolve_non_region_params(tests_params)
                    output = io.StringIO()
                    iact3_yaml.dump({'parameters': tests_params}, output)
                    params_yaml = output.getvalue()
                    response_data = {'parameters': params_yaml}
                    if tf_variables:
                        tf_log_lines = [f'Found {len(tf_variables)} Terraform variable(s):']
                        for vname, vinfo in tf_variables.items():
                            parts = [f'  - {vname}']
                            if vinfo.get('type'):
                                parts.append(f'  type={vinfo["type"]}')
                            if vinfo.get('default') is not None:
                                parts.append(f'  default={vinfo["default"]}')
                            tf_log_lines.append('  '.join(parts))
                        response_data['logs'] = '\n'.join(tf_log_lines)
                    else:
                        response_data['logs'] = 'No Terraform variables found in .tf files.'
                    response_data['logs'] += f'\nMulti-region mode ({len(region_list)} regions): region-specific params kept as $[iact3-auto] for runtime per-region resolution.'
                    return web.json_response(response_data)
                tests_params = await _resolve_terraform_params(tests_params, region, credential)
                output = io.StringIO()
                iact3_yaml.dump({'parameters': tests_params}, output)
                params_yaml = output.getvalue()
                response_data = {'parameters': params_yaml}
                if is_multi_region:
                    response_data['logs'] = (response_data.get('logs') or '') + f'\nMulti-region mode ({len(region_list)} regions): region-specific params kept as $[iact3-auto] for runtime per-region resolution.'
                if tf_variables:
                    tf_log_lines = [f'Found {len(tf_variables)} Terraform variable(s):']
                    for vname, vinfo in tf_variables.items():
                        parts = [f'  - {vname}']
                        if vinfo.get('type'):
                            parts.append(f'  type={vinfo["type"]}')
                        if vinfo.get('default') is not None:
                            parts.append(f'  default={vinfo["default"]}')
                        tf_log_lines.append('  '.join(parts))
                    response_data['logs'] = '\n'.join(tf_log_lines)
                else:
                    response_data['logs'] = 'No Terraform variables found in .tf files.'
                return web.json_response(response_data)
            
            # Build TestConfig for ParamGenerator directly (bypass from_dict/schema
            # validation).  The Auth schema does not handle Optional[str] correctly
            # (generates {"type": "string"} instead of anyOf), so from_dict() fails
            # when Auth.name is None.  Direct construction avoids this.
            test_config = TestConfig(
                auth=Auth(),
                template_config=template_config,
                parameters=tests_params,
            )
            # region and test_name are NOT dataclass fields of TestConfig;
            # TestConfig.__post_init__ resets them to None, so assign after construction.
            test_config.region = region
            test_config.test_name = 'default'
            # Inject the resolved credential directly so ParamGenerator can use it
            # (otherwise Auth._get_credential would try to read ~/.iact3.json again).
            test_config.auth.credential = credential
            
            if credential is None:
                return web.json_response(
                    {'error': '未找到阿里云凭证，无法自动生成参数。请在配置中设置 auth 部分，或先在 ~/.aliyun/config.json 中配置阿里云凭证。'},
                    status=400
                )
            
            if is_multi_region:
                # Multi-region mode: keep region-specific params as $[iact3-auto]
                # for runtime per-region resolution. Only resolve non-region params.
                resolved_params = _resolve_non_region_params(tests_params)
                output = io.StringIO()
                iact3_yaml.dump({'parameters': resolved_params}, output)
                params_yaml = output.getvalue()
                response_data = {
                    'parameters': params_yaml,
                    'logs': f'Multi-region mode ({len(region_list)} regions): region-specific params kept as $[iact3-auto] for runtime per-region resolution.'
                }
                return web.json_response(response_data)
            
            # Generate parameters (capture logs for UI display)
            log_buf = io.StringIO()
            log_handler = _logging.StreamHandler(log_buf)
            log_handler.setLevel(_logging.DEBUG)
            log_handler.setFormatter(_logging.Formatter('%(levelname)s: %(message)s'))
            gen_logger = _logging.getLogger('iact3.generate_params')
            old_level = gen_logger.level
            gen_logger.setLevel(_logging.DEBUG)
            gen_logger.addHandler(log_handler)
            try:
                result = await ParamGenerator.result(test_config)
            finally:
                gen_logger.removeHandler(log_handler)
                gen_logger.setLevel(old_level)
            captured_logs = log_buf.getvalue()
            
            # Convert to YAML format: wrap under `parameters:` so the result can be
            # directly pasted into the iact3 config file under tests.<name>.parameters.
            output = io.StringIO()
            iact3_yaml.dump({'parameters': result.parameters}, output)
            params_yaml = output.getvalue()
            
            # If there were errors, include them as warnings rather than failing.
            # Parameters that couldn't be resolved will keep their $[iact3-auto] placeholder.
            response_data = {'parameters': params_yaml}
            if captured_logs:
                response_data['logs'] = captured_logs
            if result.error:
                LOG.warning(f'[generate-params] Partial resolution completed with error: {result.error}')
                response_data['warning'] = str(result.error)
            
            return web.json_response(response_data)
        except Exception as ex:
            LOG.error(f'[generate-params] FAILED: {ex}', exc_info=True)
            return web.json_response({'error': str(ex)}, status=500)
        finally:
            _cleanup_current_files(subdir=tf_subdir)

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

    def _detect_aliyun_cli_credentials():
        """Read profiles from ~/.aliyun/config.json if present."""
        profiles = []
        current = None
        creds = {}
        try:
            if DEFAULT_AUTH_FILE.is_file():
                with open(DEFAULT_AUTH_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                current = data.get('current')
                for profile in data.get('profiles', []):
                    profiles.append({
                        'name': profile.get('name'),
                        'mode': profile.get('mode'),
                    })
                    if profile.get('name') == (current or profile.get('name')):
                        creds = {
                            'access_key_id': profile.get('access_key_id', ''),
                            'access_key_secret': profile.get('access_key_secret', ''),
                            'security_token': profile.get('sts_token', ''),
                        }
        except Exception as ex:
            LOG.debug(f'Failed to read aliyun CLI config: {ex}')
        return profiles, current, creds

    def _detect_env_credentials():
        """Check whether Alibaba Cloud credential env vars are set."""
        ak = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID') or os.environ.get('ALIBABA_CLOUD_ACCESS_KEY')
        sk = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET') or os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET')
        return bool(ak and sk)

    def _resolve_credential_source():
        """Determine where usable credentials come from."""
        if _detect_env_credentials():
            return 'env'
        _, _, cli_creds = _detect_aliyun_cli_credentials()
        if cli_creds.get('access_key_id') and cli_creds.get('access_key_secret'):
            return 'aliyun-cli'
        return 'none'

    async def get_settings(request):
        """GET /api/settings - Detect credential source from CLI / env."""
        profiles, current_profile, cli_creds = _detect_aliyun_cli_credentials()
        source = _resolve_credential_source()

        return web.json_response({
            'settings': {
                'source': source,
                'credentials_set': source != 'none',
                'aliyun_cli_available': bool(profiles),
                'aliyun_profiles': profiles,
                'aliyun_current_profile': current_profile,
            }
        })

    async def get_credentials(request):
        """GET /api/credentials - Detect local Alibaba Cloud credentials."""
        profiles, current_profile, cli_creds = _detect_aliyun_cli_credentials()
        env_set = _detect_env_credentials()
        source = 'none'
        if env_set:
            source = 'env'
        elif cli_creds.get('access_key_id') and cli_creds.get('access_key_secret'):
            source = 'aliyun-cli'

        return web.json_response({
            'source': source,
            'env_set': env_set,
            'aliyun_cli_available': bool(profiles),
            'profiles': profiles,
            'current_profile': current_profile,
            'current_profile_key_id_tail': ('****' + cli_creds.get('access_key_id', '')[-4:])
            if cli_creds.get('access_key_id') and len(cli_creds.get('access_key_id', '')) > 4 else '',
        })

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

        config_path = (DEFAULT_PROJECT_ROOT / config_file).resolve()
        # Security: ensure config_path is within the project root
        if not _is_path_within(config_path, [DEFAULT_PROJECT_ROOT]):
            return web.json_response({'error': 'Invalid config_file path'}, status=403)
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
        if not _is_file_path_allowed(resolved):
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
        if not _is_file_path_allowed(resolved):
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
            regions = await plugin.get_regions_with_names(lang=lang)
            # Filter to only standard public regions
            regions = [r for r in regions if _STANDARD_REGION_RE.match(r['id'])]
            return web.json_response({'regions': regions})
        except Exception as ex:
            err_msg = str(ex)
            if 'credentials' in err_msg.lower():
                LOG.debug('Using fallback region list (credentials not configured)')
            else:
                LOG.warning(f'Failed to fetch regions from API, using fallback list: {ex}')
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

    def _extract_project_meta(template_text, config_text, template_files=None):
        """Parse template/config YAML and extract human-readable metadata.
        For Terraform projects (template_files), count the number of .tf files
        as resources and show a Terraform indicator in the description.
        """
        import yaml as _yaml

        def _has_valid_tf_files(files):
            if not files or not isinstance(files, dict):
                return False
            return any(
                bool(content) and str(fname).endswith('.tf')
                for fname, content in files.items()
            )

        is_terraform = _has_valid_tf_files(template_files)
        meta = {'is_terraform': is_terraform}
        # Parse template
        if is_terraform:
            tf_files = [f for f in template_files if str(f).endswith('.tf') and template_files[f]]
            meta['description'] = f'Terraform project ({len(tf_files)} .tf file(s))'
            meta['param_count'] = 0
            meta['resource_count'] = len(tf_files)
        else:
            try:
                tpl = _yaml.safe_load(template_text or '') or {}
                meta['description'] = (tpl.get('Description') or tpl.get('description') or '').strip()[:120]
                params = tpl.get('Parameters') or tpl.get('parameters') or {}
                meta['param_count'] = len(params) if isinstance(params, dict) else 0
                resources = tpl.get('Resources') or tpl.get('resources') or {}
                meta['resource_count'] = len(resources) if isinstance(resources, dict) else 0
            except Exception:
                meta.setdefault('description', '')
                meta.setdefault('param_count', 0)
                meta.setdefault('resource_count', 0)
        # Parse config
        try:
            cfg = _yaml.safe_load(config_text or '') or {}
            project = cfg.get('project') or {}
            meta['project_name_in_config'] = (project.get('name') or '').strip()[:60]
            tests = cfg.get('tests') or {}
            meta['test_count'] = len(tests) if isinstance(tests, dict) else 0
        except Exception:
            meta.setdefault('project_name_in_config', '')
            meta.setdefault('test_count', 0)
        return meta

    async def list_projects(request):
        """GET /api/projects - List saved template+config pairs.

        Query params:
          - search: filter by project name (case-insensitive)
          - page: 1-based page number
          - per_page: items per page (default 12, max 100)
        """
        _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        search = request.query.get('search', '').strip().lower()
        try:
            page = max(1, int(request.query.get('page', 1)))
        except ValueError:
            page = 1
        try:
            per_page = min(100, max(1, int(request.query.get('per_page', 12))))
        except ValueError:
            per_page = 12

        def _first_config(data):
            return data.get('config', '') or ''

        projects = []
        for f in sorted(_PROJECTS_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                name = data.get('name', f.stem)
                if search and search not in name.lower():
                    continue
                meta = _extract_project_meta(
                    data.get('template', '') or '',
                    _first_config(data),
                    data.get('template_files')
                )
                total_tests = 0
                try:
                    c = iact3_yaml.safe_load(data.get('config', '') or '') or {}
                    tests = c.get('tests') or {}
                    total_tests = len(tests) if isinstance(tests, dict) else 0
                except Exception:
                    pass
                projects.append({
                    'name': name,
                    'created_at': data.get('created_at', ''),
                    'updated_at': data.get('updated_at', ''),
                    'description': meta.get('description', ''),
                    'param_count': meta.get('param_count', 0),
                    'resource_count': meta.get('resource_count', 0),
                    'test_count': total_tests,
                    'project_name_in_config': meta.get('project_name_in_config', ''),
                    'is_terraform': meta.get('is_terraform', False),
                })
            except Exception:
                continue

        total = len(projects)
        start = (page - 1) * per_page
        end = start + per_page
        return web.json_response({
            'projects': projects[start:end],
            'total': total,
            'page': page,
            'per_page': per_page,
        })

    async def get_project(request):
        """GET /api/projects/{name} - Get a specific project."""
        name = request.match_info['name']
        if not _validate_project_name(name):
            return web.json_response({'error': 'Invalid project name'}, status=400)
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return web.json_response(data)

    async def get_project_runs(request):
        """GET /api/projects/{name}/runs - Get run history for a project.

        A run is considered associated with a project when:
          - run.params.project_name matches the project name, or
          - the run name equals the project name, or
          - the run's raw_template_content/raw_config_content matches the project's
            (project.name is ignored when comparing configs so renames don't break history).
        """
        name = request.match_info['name']
        if not _validate_project_name(name):
            return web.json_response({'error': 'Invalid project name'}, status=400)
        project_file = _PROJECTS_DIR / f'{name}.json'
        project = None
        if project_file.exists():
            try:
                with open(project_file, 'r', encoding='utf-8') as f:
                    project = json.load(f)
            except Exception:
                pass

        try:
            page = max(1, int(request.query.get('page', 1)))
        except ValueError:
            page = 1
        try:
            per_page = min(100, max(1, int(request.query.get('per_page', 20))))
        except ValueError:
            per_page = 20

        project_template = (project.get('template') or '') if project else ''
        project_files = project.get('template_files') if project else None
        project_config = (project.get('config') or '') if project else ''
        # Build a set of config content for matching.
        config_set = set()
        if project_config:
            config_set.add(project_config)

        def _matches(run):
            params = run.get('params') or {}
            if params.get('project_name') == name:
                return True
            if run.get('name') == name:
                return True
            # Match by raw content if project file exists.
            # Ignore project.name in config so renaming a project keeps historical runs visible.
            raw_cfg = params.get('raw_config_content', '')
            if project_template and params.get('raw_template_content') == project_template:
                return _config_matches_project(raw_cfg, config_set)
            if project_files and params.get('raw_template_files') == project_files:
                return _config_matches_project(raw_cfg, config_set)
            return False

        runs = [r for r in runner.get_all_runs() if _matches(r)]
        total = len(runs)
        start = (page - 1) * per_page
        end = start + per_page
        return web.json_response({
            'runs': runs[start:end],
            'total': total,
            'page': page,
            'per_page': per_page,
        })

    async def save_project(request):
        """POST /api/projects - Create or update a project."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)

        name = (params.get('name') or '').strip()
        if not name:
            return web.json_response({'error': 'Project name is required'}, status=400)
        if not _validate_project_name(name):
            return web.json_response(
                {'error': 'Project name must start with a letter, contain only letters, digits, hyphens (-) or underscores (_), and be at most 255 characters.'},
                status=400
            )

        old_name = (params.get('old_name') or '').strip()
        if old_name and not _validate_project_name(old_name):
            return web.json_response(
                {'error': 'Invalid old_name: must start with a letter, contain only letters, digits, hyphens (-) or underscores (_).'},
                status=400
            )
        allow_overwrite = bool(params.get('allow_overwrite', False))

        _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        project_file = _PROJECTS_DIR / f'{name}.json'

        LOG.warning(
            '[save_project] name=%s old_name=%s allow_overwrite=%s project_file=%s exists=%s',
            name, old_name, allow_overwrite, project_file, project_file.exists()
        )

        # Check for name conflict: if a different project with the new name already exists
        is_rename = bool(old_name and old_name != name)
        if project_file.exists() and (is_rename or not old_name) and not allow_overwrite:
            # Return 409 so the frontend can ask user to confirm overwrite
            LOG.warning('[save_project] returning 409 conflict for name=%s', name)
            return web.json_response({'error': 'conflict', 'name': name}, status=409)

        import time
        now = str(time.time())

        existing = None
        # Determine created_at
        if old_name and old_name != name:
            # Rename: carry over created_at from old file
            old_file = _PROJECTS_DIR / f'{old_name}.json'
            if old_file.exists():
                try:
                    with open(old_file, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                    created_at = existing.get('created_at', now)
                except Exception:
                    created_at = now
            else:
                created_at = now
        elif project_file.exists():
            try:
                with open(project_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                created_at = existing.get('created_at', now)
            except Exception:
                created_at = now
        else:
            created_at = now

        template_files = params.get('template_files')
        config = params.get('config', '')
        # Backward compatibility: accept configs array but use first config
        if not config:
            configs = params.get('configs')
            if configs and isinstance(configs, list) and len(configs) > 0:
                config = configs[0].get('config', '') or ''

        # Ensure config YAML has project.name matching the project name.
        if isinstance(config, str) and config:
            config = _sync_project_name_in_config(config, name)

        # ── Version snapshot logic ──
        # Compare new template/config with existing to decide whether to create a new version.
        MAX_VERSIONS = 20
        versions = list(existing.get('versions', [])) if existing else []
        current_version = existing.get('current_version', 0) if existing else 0

        def _config_equal(a_config, b_config):
            """Compare two config strings ignoring project.name lines."""
            a = _strip_project_name_from_config(a_config or '')
            b = _strip_project_name_from_config(b_config or '')
            return a == b

        new_template = params.get('template', '')
        new_template_files = template_files if template_files is not None else (existing.get('template_files', {}) if existing else {})

        if existing and (existing.get('template') or existing.get('config')):
            old_template = existing.get('template', '')
            old_template_files = existing.get('template_files', {})
            old_config = existing.get('config', '')
            content_changed = (
                old_template != new_template
                or old_template_files != new_template_files
                or not _config_equal(old_config, config)
            )
            if content_changed:
                # Backward compat: if current_version is a "phantom" (not in
                # versions list, from old save_project logic), save the current
                # top-level content with a new version number before overwriting.
                if versions and current_version and not any(v['version'] == current_version for v in versions):
                    phantom_ver = max(v['version'] for v in versions) + 1
                    versions.append({
                        'version': phantom_ver,
                        'template': old_template,
                        'template_files': old_template_files,
                        'config': old_config,
                        'created_at': existing.get('updated_at', existing.get('created_at', now)),
                    })
                if not versions:
                    # First ever change to this project: save initial state as v1
                    versions.append({
                        'version': 1,
                        'template': old_template,
                        'template_files': old_template_files,
                        'config': old_config,
                        'created_at': existing.get('updated_at', existing.get('created_at', now)),
                    })
                # Save NEW content as a new version so that the top-level
                # content always matches a version in the versions list.
                # This prevents data loss when activating old versions.
                new_ver = max(v['version'] for v in versions) + 1
                versions.append({
                    'version': new_ver,
                    'template': new_template,
                    'template_files': new_template_files if isinstance(new_template_files, dict) else {},
                    'config': config,
                    'created_at': now,
                })
                current_version = new_ver
                # Trim oldest versions if exceeding MAX_VERSIONS
                while len(versions) > MAX_VERSIONS:
                    versions.pop(0)
        elif not existing:
            # Brand new project: create v1
            current_version = 1
            versions = [{
                'version': 1,
                'template': new_template,
                'template_files': new_template_files if isinstance(new_template_files, dict) else {},
                'config': config,
                'created_at': now,
            }]

        data = {
            'name': name,
            'template': new_template,
            'config': config,
            'created_at': created_at,
            'updated_at': now,
            'no_delete': bool(params.get('no_delete', False)) if 'no_delete' in params else (existing.get('no_delete', False) if existing else False),
            'keep_failed': bool(params.get('keep_failed', False)) if 'keep_failed' in params else (existing.get('keep_failed', False) if existing else False),
            'dont_wait_for_delete': bool(params.get('dont_wait_for_delete', False)) if 'dont_wait_for_delete' in params else (existing.get('dont_wait_for_delete', False) if existing else False),
            'current_version': current_version,
            'versions': versions,
        }
        if template_files is not None:
            data['template_files'] = template_files
        elif existing and existing.get('template_files'):
            # Preserve existing Terraform files when frontend didn't send the field
            data['template_files'] = existing['template_files']
        with open(project_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # If renamed, remove the old file and keep historical runs associated
        if old_name and old_name != name:
            old_file = _PROJECTS_DIR / f'{old_name}.json'
            if old_file.exists():
                old_file.unlink()
            _sync_project_name_in_runs(old_name, name, runner)

        LOG.warning('[save_project] returning 200 ok for name=%s (allow_overwrite=%s)', name, allow_overwrite)
        return web.json_response({'status': 'ok', 'name': name})

    async def delete_project(request):
        """DELETE /api/projects/{name} - Delete a project."""
        name = request.match_info['name']
        if not _validate_project_name(name):
            return web.json_response({'error': 'Invalid project name'}, status=400)
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        project_file.unlink()
        return web.json_response({'status': 'deleted', 'name': name})

    async def batch_delete_projects(request):
        """POST /api/projects/batch-delete - Delete multiple projects."""
        try:
            params = await request.json()
        except json.JSONDecodeError:
            return web.json_response({'error': 'Invalid JSON'}, status=400)
        names = params.get('names') or []
        if not isinstance(names, list) or not names:
            return web.json_response({'error': 'names list is required'}, status=400)
        deleted = []
        failed = []
        for name in names:
            if not _validate_project_name(name):
                failed.append({'name': name, 'reason': 'invalid name'})
                continue
            project_file = _PROJECTS_DIR / f'{name}.json'
            try:
                if project_file.exists():
                    project_file.unlink()
                    deleted.append(name)
                else:
                    failed.append({'name': name, 'reason': 'not found'})
            except Exception as ex:
                failed.append({'name': name, 'reason': str(ex)})
        return web.json_response({'deleted': deleted, 'failed': failed})

    async def get_examples(request):
        """GET /api/projects/examples - Get example template and config."""
        return web.json_response({
            'template': _EXAMPLE_TEMPLATE,
            'config': _EXAMPLE_CONFIG,
        })

    async def list_samples(request):
        """GET /api/samples - List built-in sample templates."""
        lang = request.query.get('lang', 'zh')
        samples = []
        for sample_id, sample in _SAMPLES.items():
            if sample.get('template_files'):
                preview = f"Terraform directory ({len(sample['template_files'])} .tf file{'s' if len(sample['template_files']) > 1 else ''})"
            else:
                preview = (sample.get('template') or '')[:80].replace('\n', ' ')
            samples.append({
                'id': sample_id,
                'name': sample.get('zh_name') if lang == 'zh' else sample.get('name'),
                'template_preview': preview,
            })
        return web.json_response({'samples': samples})

    async def get_sample(request):
        """GET /api/samples/{sample_id} - Get a built-in sample."""
        sample_id = request.match_info['sample_id']
        sample = _SAMPLES.get(sample_id)
        if not sample:
            return web.json_response({'error': 'Sample not found'}, status=404)
        result = {
            'id': sample_id,
            'name': sample['name'],
            'zh_name': sample.get('zh_name'),
            'config': sample['config'],
        }
        if sample.get('template_files'):
            result['template_files'] = sample['template_files']
        else:
            result['template'] = sample['template']
        return web.json_response(result)

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

    # --- API: Project Versions ---

    async def list_project_versions(request):
        """GET /api/projects/{name}/versions - List version history (metadata only)."""
        name = request.match_info['name']
        if not _validate_project_name(name):
            return web.json_response({'error': 'Invalid project name'}, status=400)
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        versions = data.get('versions', [])
        current_version = data.get('current_version', 0)
        # If current_version is a "phantom" (not in versions), fall back to the latest version
        effective_current = current_version
        if versions and not any(v['version'] == current_version for v in versions):
            effective_current = max(v['version'] for v in versions)
        # Return metadata only (no large template/config content)
        version_list = [
            {
                'version': v['version'],
                'created_at': v.get('created_at', ''),
                'is_current': v['version'] == effective_current,
            }
            for v in versions
        ]
        return web.json_response({
            'versions': version_list,
            'current_version': effective_current,
            'total': len(versions),
        })

    async def get_project_version(request):
        """GET /api/projects/{name}/versions/{version} - Get a specific version snapshot."""
        name = request.match_info['name']
        if not _validate_project_name(name):
            return web.json_response({'error': 'Invalid project name'}, status=400)
        ver = int(request.match_info['version'])
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        versions = data.get('versions', [])
        current_version = data.get('current_version', 0)
        target = next((v for v in versions if v['version'] == ver), None)
        if not target:
            return web.json_response({'error': f'Version {ver} not found'}, status=404)
        return web.json_response({
            'version': target['version'],
            'template': target.get('template', ''),
            'template_files': target.get('template_files', {}),
            'config': target.get('config', '') or (target.get('configs', [{}])[0].get('config', '') if target.get('configs') else ''),
            'created_at': target.get('created_at', ''),
            'is_current': ver == current_version,
        })

    async def activate_project_version(request):
        """POST /api/projects/{name}/versions/{version}/activate - Set a version as current."""
        name = request.match_info['name']
        if not _validate_project_name(name):
            return web.json_response({'error': 'Invalid project name'}, status=400)
        ver = int(request.match_info['version'])
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        versions = data.get('versions', [])
        current_version = data.get('current_version', 0)
        target = next((v for v in versions if v['version'] == ver), None)
        if not target:
            return web.json_response({'error': f'Version {ver} not found'}, status=404)
        if ver == current_version:
            return web.json_response({'status': 'ok', 'message': 'Already current version', 'current_version': current_version})

        import time as _time
        now = str(_time.time())
        # Backward compat: if current_version is a "phantom" (not in versions
        # list, from old save_project logic), save the current top-level content
        # with a new version number before switching.
        if not any(v['version'] == current_version for v in versions):
            save_ver = (max(v['version'] for v in versions) + 1) if versions else 1
            versions.append({
                'version': save_ver,
                'template': data.get('template', ''),
                'template_files': data.get('template_files', {}),
                'config': data.get('config', ''),
                'created_at': data.get('updated_at', now),
            })

        # Apply target version content to top-level
        data['template'] = target.get('template', '')
        data['template_files'] = target.get('template_files', {})
        target_config = target.get('config', '')
        # Backward compat: old snapshots stored configs array
        if not target_config and target.get('configs'):
            target_config = target['configs'][0].get('config', '') or ''
        # Re-sync project.name in config
        if isinstance(target_config, str) and target_config:
            target_config = _sync_project_name_in_config(target_config, name)
        data['config'] = target_config
        data['current_version'] = ver
        data['versions'] = versions
        data['updated_at'] = now

        with open(project_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return web.json_response({
            'status': 'ok',
            'current_version': ver,
            'message': f'Activated version {ver}',
        })

    async def delete_project_version(request):
        """DELETE /api/projects/{name}/versions/{version} - Delete a version snapshot."""
        name = request.match_info['name']
        if not _validate_project_name(name):
            return web.json_response({'error': 'Invalid project name'}, status=400)
        ver = int(request.match_info['version'])
        project_file = _PROJECTS_DIR / f'{name}.json'
        if not project_file.exists():
            return web.json_response({'error': 'Project not found'}, status=404)
        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        versions = data.get('versions', [])
        current_version = data.get('current_version', 0)
        target = next((v for v in versions if v['version'] == ver), None)
        if not target:
            return web.json_response({'error': f'Version {ver} not found'}, status=404)
        if len(versions) <= 1:
            return web.json_response({'error': 'Cannot delete the last version'}, status=400)

        # Remove the version
        versions = [v for v in versions if v['version'] != ver]
        was_current = (ver == current_version)

        # If deleted version was current, set the latest version as new current
        if was_current and versions:
            latest = max(versions, key=lambda v: v['version'])
            new_current = latest['version']
            # Apply latest version content to top-level
            data['template'] = latest.get('template', '')
            data['template_files'] = latest.get('template_files', {})
            latest_config = latest.get('config', '')
            if not latest_config and latest.get('configs'):
                latest_config = latest['configs'][0].get('config', '') or ''
            if isinstance(latest_config, str) and latest_config:
                latest_config = _sync_project_name_in_config(latest_config, name)
            data['config'] = latest_config
            data['current_version'] = new_current
        elif was_current and not versions:
            # Should not happen since we checked len > 1 above
            data['current_version'] = 0
        else:
            # Backward compat: current_version might be a "phantom" (not in
            # versions list) from old save_project logic that didn't save new
            # content as a version. After deletion, ensure current_version
            # points to a valid entry.
            new_current_version = data.get('current_version', current_version)
            if versions and not any(v['version'] == new_current_version for v in versions):
                latest = max(versions, key=lambda v: v['version'])
                data['current_version'] = latest['version']

        data['versions'] = versions

        import time as _time
        data['updated_at'] = str(_time.time())

        with open(project_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        final_current = data.get('current_version', current_version)
        auto_switched = (final_current != current_version)

        return web.json_response({
            'status': 'ok',
            'deleted_version': ver,
            'current_version': final_current,
            'auto_switched': auto_switched,
            'remaining': len(versions),
        })

    # --- Register routes ---
    app.router.add_get('/api/runs', list_runs)
    app.router.add_post('/api/runs', start_run)
    app.router.add_post('/api/runs/batch-delete', batch_delete_runs)
    # Register more specific routes before the generic {run_id} route to avoid
    # aiohttp matching /api/runs/{run_id}/logs as a run_id value.
    app.router.add_get('/api/runs/{run_id}/logs', get_run_logs)
    app.router.add_get('/api/runs/{run_id}', get_run)
    app.router.add_post('/api/runs/{run_id}/cancel', cancel_run)
    app.router.add_post('/api/runs/{run_id}/delete-stacks', delete_run_stacks)
    app.router.add_delete('/api/runs/{run_id}', delete_run)

    app.router.add_post('/api/validate', validate_template)
    app.router.add_post('/api/cost', estimate_cost)
    app.router.add_post('/api/preview', preview_resources)
    app.router.add_post('/api/policy', generate_policy)
    app.router.add_post('/api/generate-params', generate_params)

    app.router.add_get('/api/reports', list_reports)
    app.router.add_get('/api/reports/{filename}/raw', get_report_raw)
    app.router.add_get('/api/reports/{filename}', get_report_file)
    app.router.add_delete('/api/reports/{filename}', delete_report)
    app.router.add_post('/api/reports/cleanup', cleanup_reports)

    app.router.add_post('/api/upload', upload_template)
    app.router.add_get('/api/templates', list_templates)
    app.router.add_delete('/api/templates/{filename}', delete_saved_file)

    app.router.add_get('/api/settings', get_settings)

    app.router.add_post('/api/config/template-path', update_config_template)

    app.router.add_get('/api/file', read_file)
    app.router.add_post('/api/file', write_file)

    app.router.add_get('/api/regions', list_regions)

    app.router.add_get('/api/projects', list_projects)
    app.router.add_post('/api/projects', save_project)
    app.router.add_post('/api/projects/batch-delete', batch_delete_projects)
    app.router.add_get('/api/projects/examples', get_examples)
    app.router.add_get('/api/projects/{name}/runs', get_project_runs)
    app.router.add_get('/api/projects/{name}/versions', list_project_versions)
    app.router.add_get('/api/projects/{name}/versions/{version}', get_project_version)
    app.router.add_post('/api/projects/{name}/versions/{version}/activate', activate_project_version)
    app.router.add_delete('/api/projects/{name}/versions/{version}', delete_project_version)
    app.router.add_get('/api/projects/{name}', get_project)
    app.router.add_delete('/api/projects/{name}', delete_project)

    app.router.add_get('/api/samples', list_samples)
    app.router.add_get('/api/samples/{sample_id}', get_sample)

    app.router.add_get('/api/credentials', get_credentials)

    app.router.add_get('/api/history', list_history)
    app.router.add_post('/api/history/cleanup', cleanup_history)
    app.router.add_get('/api/history/{id}', get_history)
    app.router.add_delete('/api/history/{id}', delete_history)
