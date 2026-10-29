from unittest import mock

from iact3.cli_modules.list import List
from iact3.stack import IAC_NAME, SYS_TAGS
from tests.common import AsyncTestCase


class TestListStacks(AsyncTestCase):
    async def test_explicit_regions_and_tags_are_forwarded(self):
        calls = []

        class Plugin:
            def __init__(self, region_id, credential):
                self.region = region_id
            async def fetch_all_stacks(self, tags, stack_id=None):
                calls.append((self.region, dict(tags), stack_id))
                return [{'StackName': 'stack-' + self.region, 'RegionId': self.region, 'Tags': [
                    {'Key': IAC_NAME + '-test-name', 'Value': 'test'},
                    {'Key': IAC_NAME + '-project-name', 'Value': 'project'},
                    {'Key': IAC_NAME + '-id', 'Value': 'test-id'},
                ]}]

        with mock.patch.object(List, 'get_credential', return_value=object()), \
             mock.patch('iact3.cli_modules.list.StackPlugin', Plugin):
            result = await List.create(regions='cn-a,cn-b', tags={'Custom': 'value'}, stack_id='id')
        self.assertEqual({stack['RegionId'] for stack in result}, {'cn-a', 'cn-b'})
        self.assertEqual(result[0]['TestId'], 'test-id')
        self.assertTrue(all(call[1]['Custom'] == 'value' and call[2] == 'id' for call in calls))
        self.assertTrue(all(all(call[1][k] == v for k, v in SYS_TAGS.items()) for call in calls))

    async def test_no_stacks_returns_none(self):
        class Plugin:
            def __init__(self, region_id, credential):
                pass
            async def fetch_all_stacks(self, tags, stack_id=None):
                return []
        with mock.patch.object(List, 'get_credential', return_value=object()), \
             mock.patch('iact3.cli_modules.list.StackPlugin', Plugin):
            self.assertIsNone(await List.create(regions='cn-a'))
