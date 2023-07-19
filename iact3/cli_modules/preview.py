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

class Preview:
    '''
    Preview resources of templates.
    '''

    def __init__(self, template: str = None, 
                 config_file: str = DEFAULT_CONFIG_FILE,
                 regions: str = None):
        '''
        :param template: path to a template
        :param config_file: path to a config file
        :param regions: comma separated list of regions
        :return: None
        '''
        self.template = template
        self.config_file = config_file
        self.regions = regions
    
    @classmethod
    async def create(cls, template: str = None,
                     config_file: str = None,
                     regions: str = None,
                     tags: dict = None):
        tests = await StackTest.from_file(
            template=template,
            project_config_file=config_file,
            regions=regions
        )
        LOG.info(f'start previewing templates.')
        await StackTest.preview_stacks_result(tests)