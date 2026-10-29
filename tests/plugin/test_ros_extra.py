import json

from Tea.exceptions import TeaException

from iact3.plugin.ros import StackPlugin
from tests.common import AsyncTestCase


class TestRosRequestHandling(AsyncTestCase):
    def setUp(self):
        self.plugin = StackPlugin(region_id='cn-test', credential=object())

    def test_parameters_are_serialized_and_none_is_omitted(self):
        kwargs = {}
        self.plugin._convert_parameters({'List': [1, 2], 'Map': {'a': 1}, 'Flag': False,
                                         'Number': 2, 'Empty': None}, kwargs)
        values = {item['ParameterKey']: item['ParameterValue'] for item in kwargs['Parameters']}
        self.assertEqual(json.loads(values['List']), [1, 2])
        self.assertEqual(json.loads(values['Map']), {'a': 1})
        self.assertEqual(values['Flag'], 'false')
        self.assertEqual(values['Number'], '2')
        self.assertNotIn('Empty', values)
        with self.assertRaises(AssertionError):
            self.plugin._convert_parameters(['invalid'], {})
        with self.assertRaises(AssertionError):
            self.plugin._convert_notification_urls('invalid', {})

    async def test_create_stack_converts_tags_and_notification_urls(self):
        calls = []
        async def send(action, **kwargs):
            calls.append((action, kwargs))
            return {'StackId': 'stack'}
        self.plugin.send_request = send
        self.assertEqual(await self.plugin.create_stack('name', parameters={'Flag': True},
                                                        tags={'owner': 'test'}, notification_urls=['https://example.invalid']), 'stack')
        action, kwargs = calls[0]
        self.assertEqual(action, 'CreateStackRequest')
        self.assertEqual(kwargs['Parameters'], [{'ParameterKey': 'Flag', 'ParameterValue': 'true'}])
        self.assertEqual(kwargs['Tags'], [{'Key': 'owner', 'Value': 'test'}])
        self.assertEqual(kwargs['NotificationUrls'], ['https://example.invalid'])

    async def test_missing_stack_is_ignored_but_other_errors_propagate(self):
        async def missing(action, **kwargs):
            raise TeaException({'code': 'StackNotFound', 'message': 'missing'})
        self.plugin.send_request = missing
        self.assertFalse(await self.plugin.delete_stack('stack'))
        self.assertIsNone(await self.plugin.get_stack('stack'))
        async def denied(action, **kwargs):
            raise TeaException({'code': 'Forbidden', 'message': 'denied'})
        self.plugin.send_request = denied
        with self.assertRaises(TeaException):
            await self.plugin.delete_stack('stack')
        with self.assertRaises(TeaException):
            await self.plugin.get_stack('stack')

    async def test_region_localization_and_resource_arguments(self):
        calls = []
        async def send(action, **kwargs):
            calls.append((action, kwargs))
            if action == 'DescribeRegionsRequest':
                return {'Regions': [{'RegionId': 'cn-a', 'LocalName': 'A'}, {'RegionId': 'cn-b'}]}
            return {'ok': True}
        self.plugin.send_request = send
        self.assertEqual(await self.plugin.get_regions('zh'), ['cn-a', 'cn-b'])
        self.assertEqual(await self.plugin.get_regions_with_names('en'), [{'id': 'cn-a', 'name': 'A'}, {'id': 'cn-b', 'name': 'cn-b'}])
        self.assertEqual(calls[0][1]['AcceptLanguage'], 'zh-CN')
        self.assertEqual(calls[1][1]['AcceptLanguage'], 'en-US')
        await self.plugin.get_stack_resource('stack', 'r', show_resource_attributes=True)
        self.assertEqual(calls[-1][1]['ShowResourceAttributes'], 'true')
        await self.plugin.get_stack_resource('stack', 'r', resource_attributes=['A'])
        self.assertEqual(calls[-1][1]['ResourceAttributes'], ['A'])
