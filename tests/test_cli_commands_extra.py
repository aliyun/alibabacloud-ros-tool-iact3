from types import SimpleNamespace
from unittest import mock

from iact3.cli_modules import cost, delete, policy, preview, validate
from tests.common import AsyncTestCase


class TestCommandInputs(AsyncTestCase):
    def test_command_constructors_store_arguments(self):
        for cls in (cost.Cost, policy.Policy, preview.Preview, validate.Validate):
            command = cls(template='template', config_file='config', regions='cn-a')
            self.assertEqual((command.template, command.config_file, command.regions), ('template', 'config', 'cn-a'))
        command = delete.Delete(regions='cn-a', config_file='config', project_path='project')
        self.assertEqual((command.regions, command.config_file, command.project_path), ('cn-a', 'config', 'project'))

    async def test_validate_and_policy_use_first_config_credential_and_template(self):
        for module, cls, operation, display in (
            (validate, validate.Validate, 'validate_template', '_display_validation'),
            (policy, policy.Policy, 'generate_template_policy', '_display_policies'),
        ):
            credential = object()
            template = SimpleNamespace(generate_template_args=lambda: {'template_body': 'body'})
            config = SimpleNamespace(auth=SimpleNamespace(credential=credential), template_config=template)
            base_config = SimpleNamespace(tests={'default': config})
            async def request(**kwargs):
                self.assertEqual(kwargs, {'template_body': 'body'})
                return {'result': 'ok'}
            plugin = mock.Mock()
            setattr(plugin, operation, request)
            with mock.patch.object(module.BaseConfig, 'create', return_value=base_config) as create, \
                 mock.patch.object(module, 'StackPlugin', return_value=plugin) as factory, \
                 mock.patch.object(module.TerminalPrinter, display) as printer:
                await cls.create(config_file='config', regions='cn-a,cn-b')
            self.assertEqual(create.call_args[1]['args']['project']['regions'], ['cn-a', 'cn-b'])
            factory.assert_called_once_with(region_id=None, credential=credential)
            printer.assert_called_once()

    async def test_delete_empty_and_batched_stacks(self):
        calls = []
        async def find(*args, **kwargs):
            return []
        with mock.patch.object(delete.List, 'get_credential', return_value='credential'), \
             mock.patch.object(delete.List, 'create', find):
            await delete.Delete.create(regions='cn-a')
        async def find_many(*args, **kwargs):
            return [{'StackId': str(i)} for i in range(12)]
        async def remove():
            calls.append('delete')
        async def report(stacker):
            calls.append('report')
        stacker = SimpleNamespace(delete_stacks=remove)
        printer = SimpleNamespace(report_test_progress=report)
        with mock.patch.object(delete.List, 'get_credential', return_value='credential'), \
             mock.patch.object(delete.List, 'create', find_many), \
             mock.patch.object(delete.Stack, 'from_stack_response', side_effect=lambda data, credential: data), \
             mock.patch.object(delete.Stacker, 'from_stacks', return_value=stacker), \
             mock.patch.object(delete, 'TerminalPrinter', return_value=printer):
            await delete.Delete.create(regions='cn-a')
        self.assertEqual(calls, ['delete', 'report', 'delete', 'report'])
