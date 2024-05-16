# -*- coding: utf-8 -*-
import logging

from iact3.cli_modules.list import List
from iact3.stack import Stacks, Stack, Stacker
from iact3.termial_print import TerminalPrinter

LOG = logging.getLogger(__name__)
LIMIT = 10


class Delete:
    '''
    Manually clean up the stacks which were created by Iact3
    '''

    def __init__(self, regions: str = None, config_file: str = None, project_path: str = None):
        '''
        :param regions: comma separated list of regions to delete from, default will scan all regions
        :param config_file: path to a config file
        :param project_path: root path of the project relative to config file
        '''
        self.regions = regions
        self.config_file = config_file
        self.project_path = project_path

    @classmethod
    async def create(cls, regions: str = None,
                     config_file: str = None,
                     project_path: str = None,
                     tags: dict = None,
                     stack_id: str = None):
        credential = List.get_credential(config_file, project_path)
        all_stacks = await List.create(regions, config_file, project_path, tags, stack_id=stack_id)
        if not all_stacks:
            LOG.info('can not find stack to delete.')
            return
        LOG.info('Start delete above stacks')
        printer = TerminalPrinter()

        for i in range(0, len(all_stacks), LIMIT):
            stacks = Stacks()
            stacks += [Stack.from_stack_response(stack, credential=credential) for stack in all_stacks[i: i+LIMIT]]
            stacker = Stacker.from_stacks(stacks)
            await stacker.delete_stacks()
            await printer.report_test_progress(stacker)
