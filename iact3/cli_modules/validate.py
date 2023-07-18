import json
import logging
import asyncio

from iact3.cli import CliCore
from iact3.cli_modules.delete import Delete
from iact3.cli_modules.list import List

from iact3.testing.ros_stack import StackTest
from iact3.config import BaseConfig, PROJECT, REGIONS, TEMPLATE_CONFIG, TESTS, TestConfig, IAC_NAME, \
    DEFAULT_PROJECT_ROOT, OssConfig, Auth, TEMPLATE_LOCATION, DEFAULT_CONFIG_FILE, DEFAULT_OUTPUT_DIRECTORY
from iact3.exceptions import Iact3Exception

from iact3.config import TemplateConfig
from iact3.plugin.ros import StackPlugin
from iact3.termial_print import TerminalPrinter

LOG = logging.getLogger(__name__)

class Validate:
    '''
    Validate the templates.
    '''

    def __init__(self, template: str = None, 
                 config_file: str = DEFAULT_CONFIG_FILE,
                 regions: str = None):
        '''
        :param template: path to a template
        :param config_file: path to a config file
        :param regions: comma separated list of regions
        '''
        self.template = template
        self.config_file = config_file
        self.regions = regions
    
    
    @classmethod
    async def create(cls, template: str = None,
                     config_file: str = None,
                     regions: str = None):
        
        LOG.info(f'start validating template.')
        # tests = await StackTest.from_file(
        #     template=template,
        #     project_config_file=config_file,
        #     regions=regions
        # )
        results = []
        test_names = []
        args = {}
        if regions:
            args[REGIONS] = regions.split(',')

        project_path = DEFAULT_PROJECT_ROOT


        if template:
            template_config = TemplateConfig(template_location=template)
            template_args = template_config.generate_template_args()
            plugin = StackPlugin(region_id=None, credential=None)
            results.append(await plugin.validate_template(
                **template_args
            ))
        else:
            base_config = BaseConfig.create(
                project_config_file=config_file or DEFAULT_CONFIG_FILE,
                args={PROJECT: args},
                project_path=project_path
            )
            validate_tasks = []
            for test_name, test_config in base_config.tests.items():
                credential = test_config.auth.credential
                template_config = test_config.template_config
                template_args = template_config.generate_template_args()
                plugin = StackPlugin(region_id=None, credential=credential)
                validate_tasks.append(
                    asyncio.create_task(plugin.validate_template(
                        **template_args
                    )))
                test_names.append(test_name)
            results += await asyncio.gather(*validate_tasks)

        TerminalPrinter._display_validation(template_validation=results, test_names=test_names)    

        
        
        

        # await StackTest.get_stacks_price(tests)


        # args = {}
        # args["template_config"] = {"template_config": template}
        # merged_test_configs = {
        #     key: cls.merge(merged_project_config, value) for key, value in config.get(TESTS, {}).items()
        # }
        # debug = BaseConfig.from_dict({
        #     "TESTS": args
        # })
        # debug2 = 0

        # await StackTest.validate_templates(tests)