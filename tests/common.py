import json
import os
import sys
from pathlib import Path
from unittest import mock

from alibabacloud_ros20190910 import models as ros_models
from iact3.logger import init_cli_logger
from iact3.plugin.base_plugin import TeaSDKPlugin

if sys.version_info >= (3, 8):
    from unittest import IsolatedAsyncioTestCase as AsyncTestCase
else:
    from asynctest import TestCase as AsyncTestCase


def _mock_price_resources():
    def price(resource_type):
        return {
            'Type': resource_type,
            'Result': {
                'OrderSupplement': {
                    'ChargeType': 'PostPaid',
                    'PriceUnit': 'Hour',
                    'Quantity': 1,
                },
                'Order': {
                    'Currency': 'CNY',
                    'OriginalAmount': 1,
                    'DiscountAmount': 0,
                    'TradeAmount': 1,
                },
            },
        }

    resources = {
        'SlaveConsulServer': price('ALIYUN::ECS::InstanceGroup'),
        'EcsInstance': price('ALIYUN::ECS::Instance'),
        'ElasticIp': price('ALIYUN::VPC::EIP'),
    }
    resources['ElasticIp']['Result']['AssociationFlow'] = price('ALIYUN::VPC::EIP-AssociationFlow')
    return resources


def _mock_stack(stack_id='mock-stack-id', region='cn-shanghai', stack_name='iact3-mock-stack'):
    return {
        'StackId': stack_id,
        'StackName': stack_name,
        'RegionId': region,
        'Status': 'CREATE_COMPLETE',
        'StatusReason': 'Stack created by test mock',
        'Outputs': [
            {'OutputKey': 'Key1', 'OutputValue': 'Value1'},
            {'OutputKey': 'EcsInstanceId', 'OutputValue': 'i-mock'},
        ],
        'Tags': [
            {'Key': 'iact3-test-name', 'Value': 'default'},
            {'Key': 'iact3-project-name', 'Value': 'mock-project'},
            {'Key': 'iact3-id', 'Value': 'mock-id'},
        ],
    }


def _mock_preview_resources():
    resources = [
        {
            'LogicalResourceId': 'EIP',
            'ResourceType': 'ALIYUN::VPC::EIP',
            'Properties': {
                'Bandwidth': 1,
                'InternetChargeType': 'PayByTraffic',
            },
        },
        {
            'LogicalResourceId': 'EipBind',
            'ResourceType': 'ALIYUN::VPC::EIPAssociation',
            'Properties': {
                'AllocationId': 'EIP',
                'InstanceId': 'EcsInstance',
            },
        },
        {
            'LogicalResourceId': 'SlaveConsulServer',
            'ResourceType': 'ALIYUN::ECS::InstanceGroup',
            'Properties': {
                'AdjustmentType': 'NoEffect',
            },
        },
    ]
    for index in range(30):
        resources.append(
            {
                'LogicalResourceId': f'MockResource{index}',
                'ResourceType': 'ALIYUN::ROS::Sleep',
                'Properties': {'CreateDuration': 1},
            }
        )
    resources.append(
        {
            'LogicalResourceId': 'RosWaitCondition',
            'ResourceType': 'ALIYUN::ROS::WaitCondition',
            'Properties': {'Timeout': 1},
        }
    )
    return resources


def _mock_template_body():
    return (Path(__file__).parent / 'data' / 'ecs_instance.template.json').read_text()


def _has_invalid_disk(kwargs):
    for param in kwargs.get('Parameters') or []:
        if param.get('ParameterKey') == 'EcsSystemDiskCategory' and param.get('ParameterValue') == 'cloud_esd':
            return True
    return False


def _mock_template_validation(kwargs):
    template_body = kwargs.get('TemplateBody') or ''
    template_url = kwargs.get('TemplateURL') or ''
    if (
        'NatGateway' in template_body
        or 'Create an IPv4 VPC' in template_body
        or 'invalid' in template_url
        or template_url == 'http://1.yaml'
    ):
        return {
            'Code': 'InvalidTemplate',
            'Message': 'Invalid template from test mock',
        }
    return {}


async def _mock_send_request(plugin, request_name: str, ignore_exception: bool = False, **kwargs):
    if request_name.endswith('Request'):
        request_name = request_name[: -len('Request')]

    if request_name == 'DescribeRegions':
        return {'Regions': [{'RegionId': 'cn-hangzhou'}, {'RegionId': 'cn-beijing'}, {'RegionId': 'cn-shanghai'}]}
    if request_name == 'CreateStack':
        return {'StackId': 'mock-stack-id'}
    if request_name == 'DeleteStack':
        return {}
    if request_name == 'GetStack':
        return _mock_stack(stack_id=kwargs.get('StackId', 'mock-stack-id'), region=plugin.region_id or 'cn-hangzhou')
    if request_name == 'ListStacks':
        region = plugin.region_id or kwargs.get('RegionId') or 'cn-hangzhou'
        return {
            'Stacks': [_mock_stack(region=region, stack_name=f'iact3-default-{region}')],
            'TotalCount': 1,
            'PageNumber': kwargs.get('PageNumber', 1),
            'PageSize': kwargs.get('PageSize', 50),
        }
    if request_name == 'ListStackResources':
        return {
            'Resources': [
                {
                    'LogicalResourceId': 'sleep',
                    'ResourceType': 'ALIYUN::ROS::Sleep',
                    'Status': 'CREATE_COMPLETE',
                    'PhysicalResourceId': 'sleep-mock',
                }
            ],
            'TotalCount': 1,
        }
    if request_name == 'ListStackEvents':
        return {
            'Events': [
                {
                    'EventId': 'event-mock',
                    'StackName': 'iact3-mock-stack',
                    'LogicalResourceId': 'sleep',
                    'ResourceType': 'ALIYUN::ROS::Sleep',
                    'Status': 'CREATE_COMPLETE',
                    'CreateTime': '2026-01-01T00:00:00',
                    'StatusReason': 'created by test mock',
                }
            ],
            'TotalCount': 1,
        }
    if request_name == 'GetStackResource':
        return {
            'Resource': {
                'LogicalResourceId': kwargs.get('LogicalResourceId', 'sleep'),
                'ResourceType': 'ALIYUN::ROS::Sleep',
                'Status': 'CREATE_COMPLETE',
            }
        }
    if request_name == 'GetTemplateParameterConstraints':
        key = (kwargs.get('ParametersKeyFilter') or ['ZoneId'])[0]
        values_by_key = {
            'ZoneId': ['cn-hangzhou-h', 'cn-beijing-h', 'cn-shanghai-h'],
            'InstanceType': ['ecs.g6.large', 'ecs.g6e.large'],
            'SystemDiskCategory': ['cloud_ssd', 'cloud_essd'],
            'DataDiskCategory': ['cloud_ssd', 'cloud_essd'],
            'DBInstanceClass': ['mysql.n2.medium.1'],
        }
        return {'ParameterConstraints': [{'AllowedValues': values_by_key.get(key, ['mock-value'])}]}
    if request_name == 'GetTemplate':
        return {'TemplateBody': _mock_template_body()}
    if request_name == 'GetTemplateEstimateCost':
        if _has_invalid_disk(kwargs):
            from Tea.exceptions import TeaException

            raise TeaException({'code': 'StackValidationFailed', 'message': 'code: mocked invalid disk'})
        return {'Resources': _mock_price_resources()}
    if request_name == 'ValidateTemplate':
        return _mock_template_validation(kwargs)
    if request_name == 'PreviewStack':
        if _has_invalid_disk(kwargs):
            from Tea.exceptions import TeaException

            raise TeaException({'code': 'StackValidationFailed', 'message': 'code: mocked invalid disk'})
        return {'Stack': {'Resources': _mock_preview_resources()}}
    if request_name == 'GenerateTemplatePolicy':
        template_body = kwargs.get('TemplateBody') or ''
        if 'ROS::Sleep' in template_body or 'NatGateway' in template_body:
            return {'Policy': {'Version': '1', 'Statement': []}}
        return {'Policy': {'Version': '1', 'Statement': [{'Action': ['*'], 'Resource': ['*'], 'Effect': 'Allow'}]}}
    if request_name == 'DescribeVpcs':
        return {
            'Vpcs': {
                'Vpc': [
                    {
                        'VpcId': 'vpc-mock',
                        'VSwitchIds': {'VSwitchId': ['vsw-mock']},
                    }
                ]
            }
        }
    if request_name == 'DescribeVSwitches':
        return {
            'VSwitches': {
                'VSwitch': [
                    {
                        'VpcId': kwargs.get('VpcId') or 'vpc-mock',
                        'VSwitchId': kwargs.get('VSwitchId') or 'vsw-mock',
                        'ZoneId': kwargs.get('ZoneId') or 'cn-hangzhou-h',
                        'AvailableIpAddressCount': 8,
                    }
                ]
            }
        }
    if request_name == 'DescribeSecurityGroups':
        return {
            'SecurityGroups': {
                'SecurityGroup': [
                    {
                        'SecurityGroupId': 'sg-mock',
                        'ServiceManaged': False,
                    }
                ]
            },
            'TotalCount': 1,
        }
    raise AssertionError(f'Unhandled mocked request: {request_name}')


class _FakeOssObject:
    content_length = 128

    def read(self):
        return _mock_template_body().encode()


class _FakeBucket:
    def __init__(self, *args, **kwargs):
        self.objects = {}

    def put_object(self, object_name, content, params=None):
        self.objects[object_name] = content

    def put_object_from_file(self, object_name, local_file):
        self.objects[object_name] = local_file

    def object_exists(self, object_name):
        return True

    def get_object(self, object_name):
        return _FakeOssObject()

    def get_object_meta(self, object_name):
        return _FakeOssObject()

    def get_bucket_info(self):
        return {'name': 'mock-bucket'}


class _FakeHttpResponse:
    def __init__(self, body):
        self.body = body.encode() if isinstance(body, str) else body

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1000):
        yield self.body


class BaseTest(AsyncTestCase):
    REGION_ID = 'cn-shanghai'

    DATA_PATH = Path(__file__).parent / 'data'

    def setUp(self) -> None:
        init_cli_logger(loglevel='Debug')
        self._patchers = [
            mock.patch.dict(
                os.environ,
                {
                    'ALIBABA_CLOUD_ACCESS_KEY_ID': 'test_ak',
                    'ALIBABA_CLOUD_ACCESS_KEY_SECRET': 'test_sk',
                },
            ),
            mock.patch('alibabacloud_credentials.utils.auth_util.environment_access_key_id', 'test_ak'),
            mock.patch('alibabacloud_credentials.utils.auth_util.environment_access_key_secret', 'test_sk'),
            mock.patch.object(TeaSDKPlugin, 'send_request', new=_mock_send_request),
            mock.patch('oss2.Bucket', new=_FakeBucket),
            mock.patch('requests.get', return_value=_FakeHttpResponse(_mock_template_body())),
            mock.patch(
                'alibabacloud_ros20190910.client.Client.list_stacks_with_options_async',
                new=self._mock_sdk_list_stacks,
            ),
        ]
        for patcher in self._patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    async def _mock_sdk_list_stacks(*args, **kwargs):
        body = ros_models.ListStacksResponseBody()
        body.stacks = [
            ros_models.ListStacksResponseBodyStacks(
                stack_id='mock-stack-id',
                stack_name='iact3-default-cn-hangzhou',
                region_id='cn-hangzhou',
                status='CREATE_COMPLETE',
            )
        ]
        body.total_count = 1
        return ros_models.ListStacksResponse(body=body)

    @staticmethod
    def _pprint_json(data, ensure_ascii=False):
        print(json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '), ensure_ascii=ensure_ascii))

    @staticmethod
    def _log_messages(memory_handler):
        return [record.getMessage() for record in memory_handler.buffer]

    def assert_any_log_contains(self, memory_handler, text):
        messages = self._log_messages(memory_handler)
        if not any(text in message for message in messages):
            self.fail(f'{text!r} not found in log messages: {messages!r}')

    def assert_any_log_equals(self, memory_handler, text):
        messages = self._log_messages(memory_handler)
        if text not in messages:
            self.fail(f'{text!r} not found in log messages: {messages!r}')
