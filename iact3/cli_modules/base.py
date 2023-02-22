# -*- coding: utf-8 -*-
import uuid

from iact3.cli import CliCore
from iact3.cli_modules import Delete, List
from iact3.config import TestConfig
from iact3.plugin.ros import StackPlugin
from iact3.stack import Stacker
from iact3.termial_print import TerminalPrinter

BASIC_RESOURCE_TEMPLATE = '''
ROSTemplateFormatVersion: '2015-09-01'
Resources:
  SecurityGroup:
    Type: ALIYUN::ECS::SecurityGroup
    Properties:
      SecurityGroupIngress:
        - Priority: 1
          IpProtocol: all
          NicType: internet
          SourceCidrIp: 0.0.0.0/0
          PortRange: '-1/-1'
      VpcId:
        Ref: Vpc
      SecurityGroupName: iact3
  VSwitch:
    Type: ALIYUN::ECS::VSwitch
    Count:
      Fn::Length:
        Fn::GetAZs:
          Ref: ALIYUN::Region
    Properties:
      VSwitchName:
        Fn::Sub:
          - iact3-${zone}
          - zone:
              Fn::Select:
                - Ref: ALIYUN::Index
                - Fn::GetAZs:
                    Ref: ALIYUN::Region
      VpcId:
        Ref: Vpc
      CidrBlock:
        Fn::Sub: 192.168.${ALIYUN::Index}.0/24
      ZoneId:
        Fn::Select:
          - Ref: ALIYUN::Index
          - Fn::GetAZs:
              Ref: ALIYUN::Region
  Vpc:
    Type: ALIYUN::ECS::VPC
    Properties:
      VpcName: iact3
      CidrBlock: 192.168.0.0/16
'''

BASIC_RESOURCE_NAME = 'basic-resource'
BASIC_RESOURCE_TAG = {'iact3-project-name': BASIC_RESOURCE_NAME}


class Base:
    '''
    Create or delete or list basic resources which includes vpc,
    security group and several switches for testing
    '''

    @staticmethod
    @CliCore.longform_param_required('project_path')
    async def create(regions: str = None, config_file: str = None, project_path: str = None) -> None:
        '''
        Create basic resources for testing
        :param regions: comma separated list of regions to create
        :param config_file: path to a config file
        :param project_path: root path of the project relative to config file
        '''
        configs = await Base._get_config(regions, config_file, project_path)
        stacker = Stacker(
            BASIC_RESOURCE_NAME,
            configs,
            uid=uuid.uuid4()
        )
        await stacker.create_stacks()
        printer = TerminalPrinter()
        await printer.report_test_progress(stacker=stacker)

    @staticmethod
    @CliCore.longform_param_required('project_path')
    async def delete(regions: str = None, config_file: str = None, project_path: str = None) -> None:
        '''
        Delete basic resources for testing
        :param regions: comma separated list of regions to delete
        :param config_file: path to a config file
        :param project_path: root path of the project relative to config file
        '''
        await Delete.create(regions, config_file, project_path, tags=BASIC_RESOURCE_TAG)

    @staticmethod
    @CliCore.longform_param_required('project_path')
    async def list(regions: str = None,  config_file: str = None, project_path: str = None) -> None:
        '''
        List basic resources for testing
        :param regions: comma separated list of regions to list
        :param config_file: path to a config file
        :param project_path: root path of the project relative to config file
        '''
        await List.create(regions, config_file, project_path, tags=BASIC_RESOURCE_TAG)

    @staticmethod
    async def _get_config(regions: str, config_file: str = None, project_path: str = None):
        credential = List.get_credential(config_file, project_path)
        kwargs = dict(
            template_config={'template_body': BASIC_RESOURCE_TEMPLATE}
        )

        if regions:
            regions = regions.split(',')
        else:
            region_plugin = StackPlugin(region_id='cn-hangzhou', credential=credential)
            regions = await region_plugin.get_regions()

        results = []
        for region in regions:
            config = TestConfig.from_dict(kwargs)
            config.test_name = BASIC_RESOURCE_NAME
            config.auth.credential = credential
            config.region = region
            results.append(config)
        return results
