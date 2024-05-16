# -*- coding: utf-8 -*-
import asyncio
import logging

from iact3.cli import CliCore
from iact3.config import BaseConfig, DEFAULT_CONFIG_FILE, DEFAULT_PROJECT_ROOT
from iact3.generate_params import IAC_NAME
from iact3.plugin.ros import StackPlugin
from iact3.stack import SYS_TAGS

LOG = logging.getLogger(__name__)


class List:
    '''
    List stacks which were created by Iact3 for all regions.
    '''
    @CliCore.longform_param_required('project_path')
    def __init__(self, regions: str = None, config_file: str = None, project_path: str = None):
        '''
        :param regions:  comma separated list of regions to delete from, default will scan all regions
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
        credential = cls.get_credential(config_file, project_path)
        if regions:
            regions = regions.split(',')
        else:
            region_plugin = StackPlugin(region_id='cn-hangzhou', credential=credential)
            regions = await region_plugin.get_regions()
        list_tasks = []
        if tags:
            tags.update(SYS_TAGS)
        else:
            tags = SYS_TAGS
        for region in regions:
            stack_plugin = StackPlugin(region_id=region, credential=credential)
            list_tasks.append(
                asyncio.create_task(stack_plugin.fetch_all_stacks(tags, stack_id=stack_id))
            )
        stacks = await asyncio.gather(*list_tasks)
        all_stacks, project_length, test_length, stack_name_length = cls._get_all_stacks(stacks)
        if not all_stacks:
            LOG.info('can not find any stack.')
            return
        header = f'ProjectName{" "*project_length}TestName{" "*test_length}StackName{" "*stack_name_length}Region'
        LOG.info(header)
        column = '{}           {}        {}         {}'
        for stack in all_stacks:
            project_name = cls._format_name(stack['ProjectName'], project_length)
            test_name = cls._format_name(stack['TestName'], test_length)
            stack_name = cls._format_name(stack['StackName'], stack_name_length)
            LOG.info(column.format(project_name, test_name, stack_name, stack['RegionId']))
        return all_stacks

    @classmethod
    def _get_all_stacks(cls, stacks):
        all_stacks = []
        longest_project_name = ''
        longest_test_name = ''
        longest_stack_name = ''
        for region_stacks in stacks:
            for stack in region_stacks:
                stack_name = stack['StackName']
                if len(stack_name) > len(longest_stack_name):
                    longest_stack_name = stack_name
                tags = stack['Tags']
                for tag in tags:
                    if tag['Key'] == f'{IAC_NAME}-test-name':
                        test_name = tag['Value']
                        if len(test_name) > len(longest_test_name):
                            longest_test_name = test_name
                        stack['TestName'] = test_name
                    elif tag['Key'] == f'{IAC_NAME}-project-name':
                        project_name = tag['Value']
                        if len(project_name) > len(longest_project_name):
                            longest_project_name = project_name
                        stack['ProjectName'] = project_name
                    elif tag['Key'] == f'{IAC_NAME}-id':
                        stack['TestId'] = tag['Value']
                all_stacks.append(stack)

        return all_stacks, len(longest_project_name), len(longest_test_name), len(longest_stack_name)

    @classmethod
    def _format_name(cls, name, length):
        if len(name) < length:
            name += f'{" " * (length - len(name))}'
        return name

    @classmethod
    def get_credential(cls, config_file: str = None, project_path: str = None):
        base_config = BaseConfig.create(
            project_config_file=config_file or DEFAULT_CONFIG_FILE,
            project_path=project_path or DEFAULT_PROJECT_ROOT,
            fail_ok=True
        )
        return base_config.get_credential()
