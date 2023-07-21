import json
import logging

from iact3.cli import CliCore
from iact3.cli_modules.delete import Delete
from iact3.cli_modules.list import List
from iact3.config import DEFAULT_CONFIG_FILE
from iact3.testing.ros_stack import StackTest

LOG = logging.getLogger(__name__)

class Cost:
    '''
    Give the price of the templates.
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
                     regions: str = None,
                     tags: dict = None):
        tests = await StackTest.from_file(
            template=template,
            project_config_file=config_file,
            regions=regions
        )
        LOG.info(f'start querying templates costs.')
        await StackTest.get_stacks_price(tests)



    
