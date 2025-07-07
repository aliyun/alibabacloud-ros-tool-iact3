import json
import logging

from iact3.cli import CliCore
from iact3.cli_modules.delete import Delete
from iact3.cli_modules.list import List
from iact3.config import DEFAULT_CONFIG_FILE
from iact3.testing.ros_stack import StackTest

LOG = logging.getLogger(__name__)


class Test:
    '''
    Performs functional tests on IaC templates.
    '''

    @staticmethod
    @CliCore.longform_param_required('no_delete')
    @CliCore.longform_param_required('project_path')
    @CliCore.longform_param_required('test_names')
    @CliCore.longform_param_required('keep_failed')
    @CliCore.longform_param_required('dont_wait_for_delete')
    @CliCore.longform_param_required('failed')
    async def run(template: str = None,
                  config_file: str = None,
                  output_directory: str = None,
                  regions: str = None,
                  test_names: str = None,
                  no_delete: bool = False,
                  project_path: str = None,
                  keep_failed: bool = False,
                  dont_wait_for_delete: bool = False,
                  generate_parameters: bool = False,
                  log_format: str = None
                  ) -> None:
        '''
        tests whether IaC templates are able to successfully launch
        :param template: path to a template
        :param config_file: path to a config file
        :param output_directory: path to an output directory
        :param regions: comma separated list of regions to test in
        :param test_names: comma separated list of tests to run
        :param no_delete: don't delete stacks after test is complete
        :param project_path: root path of the project relative to config file, template file and output file
        :param keep_failed: do not delete failed stacks
        :param dont_wait_for_delete: exits immediately after calling delete stack
        :param generate_parameters: generate pseudo parameters
        :param log_format: comma separated list of log format (xml,json)
        :return: None
        '''
        # todo --failed param
        tests = await StackTest.from_file(
            template=template,
            project_config_file=config_file,
            no_delete=no_delete,
            regions=regions,
            project_path=project_path,
            keep_failed=keep_failed,
            dont_wait_for_delete=dont_wait_for_delete,
            test_names=test_names,
            output_directory=output_directory
        )
        if generate_parameters:
            Test._get_parameters(tests)
            return

        async with tests:
            await tests.report(log_format)

    @staticmethod
    @CliCore.longform_param_required('stack_id')
    async def clean(regions: str = None, stack_id: str = None):
        '''
        Manually clean up the stacks which were created by Iact3
        :param regions: comma separated list of regions to delete from, default will scan all regions
        :param stack_id: stack_id to delete from, default will scan all regions
        '''
        await Delete.create(regions, stack_id=stack_id)

    @staticmethod
    async def list(regions: str = None):
        '''
        List stacks which were created by Iact3 for all regions
        :param regions:  comma separated list of regions to delete from, default will scan all regions
        '''
        await List.create(regions)

    @staticmethod
    async def params(template: str = None,
                     config_file: str = DEFAULT_CONFIG_FILE,
                     regions: str = None):
        '''
        Generate pseudo parameters
        :param template: path to a template
        :param config_file: path to a config file
        :param regions: comma separated list of regions
        '''
        tests = await StackTest.from_file(
            template=template,
            project_config_file=config_file,
            regions=regions
        )
        Test._get_parameters(tests)

    @staticmethod
    def _get_parameters(tests: StackTest):
        all_configs = tests.configs
        parameters = [
            {
                'TestName': con.name,
                'TestRegion': con.region,
                'Parameters': getattr(con.error, 'message', 'GetParameterError') if con.error else con.parameters
            } for con in all_configs
        ]
        LOG.info(json.dumps(parameters, sort_keys=True, indent=4, separators=(',', ': '), ensure_ascii=False))
        return parameters
