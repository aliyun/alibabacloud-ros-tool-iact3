from unittest import mock

from iact3.cli_modules import base
from tests.common import AsyncTestCase


class TestBaseCommand(AsyncTestCase):
    async def test_explicit_and_discovered_regions(self):
        credential = object()
        async def regions():
            return ['cn-one', 'cn-two']
        plugin = mock.Mock()
        plugin.get_regions = regions
        with mock.patch.object(base.List, 'get_credential', return_value=credential), \
             mock.patch.object(base, 'StackPlugin', return_value=plugin) as factory, \
             mock.patch('iact3.config.Auth._get_credential', return_value=None):
            configs = await base.Base._get_config('cn-a,cn-b', 'config', 'project')
            self.assertEqual([c.region for c in configs], ['cn-a', 'cn-b'])
            self.assertTrue(all(c.auth.credential is credential for c in configs))
            self.assertTrue(all(c.test_name == base.BASIC_RESOURCE_NAME for c in configs))
            factory.assert_not_called()
            configs = await base.Base._get_config(None)
            self.assertEqual([c.region for c in configs], ['cn-one', 'cn-two'])
            factory.assert_called_once_with(region_id='cn-hangzhou', credential=credential)

    async def test_create_delete_and_list_use_basic_resource_tag(self):
        calls = []
        async def get_config(*args):
            calls.append(('config', args))
            return ['config']
        async def create_stacks():
            calls.append(('create',))
        async def progress(**kwargs):
            calls.append(('progress', kwargs['stacker']))
        async def delete(*args, **kwargs):
            calls.append(('delete', args, kwargs))
        async def list_stacks(*args, **kwargs):
            calls.append(('list', args, kwargs))
        stacker = mock.Mock()
        stacker.create_stacks = create_stacks
        printer = mock.Mock()
        printer.report_test_progress = progress
        with mock.patch.object(base.Base, '_get_config', get_config), \
             mock.patch.object(base, 'Stacker', return_value=stacker), \
             mock.patch.object(base, 'TerminalPrinter', return_value=printer), \
             mock.patch.object(base.Delete, 'create', delete), \
             mock.patch.object(base.List, 'create', list_stacks):
            await base.Base.create('region', 'config', 'project')
            await base.Base.delete('region', 'config', 'project')
            await base.Base.list('region', 'config', 'project')
        self.assertEqual(calls[0], ('config', ('region', 'config', 'project')))
        self.assertEqual(calls[1], ('create',))
        self.assertEqual(calls[2], ('progress', stacker))
        self.assertEqual(calls[3][2]['tags'], base.BASIC_RESOURCE_TAG)
        self.assertEqual(calls[4][2]['tags'], base.BASIC_RESOURCE_TAG)
