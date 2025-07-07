import abc
import logging
import uuid
from pathlib import Path
from typing import Any, Type, TypeVar, List, Optional

from iact3.config import BaseConfig, PROJECT, REGIONS, TEMPLATE_CONFIG, TestConfig, IAC_NAME, \
    DEFAULT_PROJECT_ROOT, OssConfig, Auth, TEMPLATE_LOCATION, DEFAULT_CONFIG_FILE, DEFAULT_OUTPUT_DIRECTORY
from iact3.exceptions import Iact3Exception
from iact3.report.generate_reports import ReportBuilder
from iact3.stack import Stacker
from iact3.termial_print import TerminalPrinter

LOG = logging.getLogger(__name__)

T = TypeVar("T", bound="Test")


class Base(metaclass=abc.ABCMeta):

    def __init__(self, project_name: str, configs: List[TestConfig],
                 no_delete: bool = False, keep_failed: bool = False,
                 dont_wait_for_delete: bool = False, rerun_failed: bool = False,
                 oss_config: OssConfig = None, auth: Auth = None,
                 report_path: Path = None
                 ):
        self.project_name = project_name
        self.configs = configs
        self.passed: bool = False
        self.result: Any = None
        self.printer = TerminalPrinter()
        self.stacker: Optional[Stacker] = None
        self.uid = uuid.uuid4()

        self.no_delete = no_delete
        self.keep_failed = keep_failed
        self.dont_wait_for_delete = dont_wait_for_delete
        self.rerun_failed = rerun_failed
        self.oss_config = oss_config
        self.auth = auth
        self.report_path = report_path

    async def __aenter__(self) -> Any:
        LOG.info(f'test {self.uid} start running.')
        try:
            await self.run()
        except BaseException as ex:
            await self.clean_up()
            raise ex

        return self.result

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.clean_up()

    @classmethod
    async def from_file(cls: Type[T],
                        template: str,
                        project_config_file: str,
                        regions: str,
                        project_path: str = None,
                        no_delete: bool = False,
                        keep_failed: bool = False,
                        dont_wait_for_delete: bool = False,
                        rerun_failed: bool = False,
                        test_names: str = None,
                        output_directory: str = None
                        ) -> T:
        args = {}
        if regions:
            args[REGIONS] = regions.split(',')
        if project_path:
            project_root = Path(project_path).expanduser().resolve()
            if template:
                template = template.lstrip('/')
                template_path = project_root / template
                args[TEMPLATE_CONFIG] = {TEMPLATE_LOCATION: str(template_path)}
            else:
                args[TEMPLATE_CONFIG] = {TEMPLATE_LOCATION: str(project_root)}
        else:
            project_root = DEFAULT_PROJECT_ROOT
            project_path = DEFAULT_PROJECT_ROOT
            if template:
                args[TEMPLATE_CONFIG] = {TEMPLATE_LOCATION: template}
        
        base_config = BaseConfig.create(
            project_config_file=project_config_file or DEFAULT_CONFIG_FILE,
            args={PROJECT: args},
            project_path=project_path
        )
        project_name = base_config.project.name
        if not project_name:
            raise Iact3Exception('project name should be specified')
        configs = await base_config.get_all_configs(test_names)

        output_directory = output_directory or DEFAULT_OUTPUT_DIRECTORY
        report_path = project_root / output_directory
        report_path.mkdir(exist_ok=True)
        return cls(project_name, configs,
                   no_delete=no_delete,
                   keep_failed=keep_failed,
                   dont_wait_for_delete=dont_wait_for_delete,
                   rerun_failed=rerun_failed,
                   oss_config=base_config.project.oss_config,
                   auth=base_config.general.auth,
                   report_path=report_path)

    async def report(self, log_format=None):
        report_path = self.report_path
        reporter = ReportBuilder(self.stacker, report_path)
        file_names = await reporter.create_logs(log_format)
        index = await reporter.generate_report()
        self._upload_to_oss(report_path, index, file_names)

    def _upload_to_oss(self, report_path: Path, index: str, file_names: list):
        oss_plugin = self.oss_config.plugin
        if oss_plugin is None:
            return

        LOG.info(f'starting upload reports to oss bucket {self.oss_config.bucket_name} '
                 f'which is in {self.oss_config.bucket_region} region')
        oss_prefix = self.oss_config.object_prefix or f'{report_path.name}-{self.uid}'
        oss_prefix = f'{IAC_NAME}/{oss_prefix}'

        for file_name in file_names:
            oss_plugin.put_local_file(f'{oss_prefix}/{file_name}', report_path / file_name)

        callback_config = self.oss_config.callback_params
        if callback_config.callback_url:
            callback_params = {
                'callbackUrl': callback_config.callback_url,
                'callbackHost': callback_config.callback_host,
                'callbackBody': callback_config.callback_body,
                'callbackBodyType': callback_config.callback_body_type,
            }
            callback_var_params = callback_config.callback_var_params
            oss_plugin.put_object_with_string(
                f'{oss_prefix}/index.html', index, callback_params, callback_var_params)
        else:
            oss_plugin.put_object_with_string(f'{oss_prefix}/index.html', index)

    @abc.abstractmethod
    async def run(self):
        raise NotImplementedError

    @abc.abstractmethod
    async def clean_up(self):
        raise NotImplementedError
