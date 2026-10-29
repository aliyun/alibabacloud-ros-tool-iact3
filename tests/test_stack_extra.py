from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from iact3.config import HookExecuteTime
from iact3.stack import Event, FilterableList, Resource, Stack, Stacker, StackStatus
from tests.common import AsyncTestCase


class TestStackHelpers(AsyncTestCase):
    def make_stack(self):
        with mock.patch('iact3.stack.StackPlugin'), mock.patch('iact3.stack.Timer'):
            return Stack(region='cn-test', stack_id='stack-id', stack_name='stack-name')

    def test_status_filter_and_stack_metadata(self):
        stack = self.make_stack()
        stack.status = 'CREATE_COMPLETE'
        self.assertTrue(stack.launch_succeeded)
        stack.status = 'DELETE_COMPLETE'
        self.assertTrue(stack.launch_succeeded)
        stack.status = 'CREATE_FAILED'
        self.assertFalse(stack.launch_succeeded)
        self.assertEqual(StackStatus.curt(stack.status), 'FAILED')
        self.assertEqual(StackStatus.curt('unknown'), 'UNKNOWN')
        self.assertEqual(StackStatus.curt('CREATE_IN_PROGRESS'), 'IN_PROGRESS')
        self.assertEqual(FilterableList([stack]).filter({'region': ['cn-test']}), [stack])
        self.assertEqual(FilterableList([stack]).filter({'region': 'other'}), [])
        with self.assertRaises(ValueError):
            FilterableList([stack]).filter({'missing': 'value'})

    def test_hook_placeholders_can_include_stack_name_and_region(self):
        self.assertEqual(Stack._replace_stack_placeholders('run $[stack.name] in $[stack.region]',
                                                           'example', 'cn-test'),
                         'run example in cn-test')
        stack = self.make_stack()
        stack.outputs = [{'OutputKey': 'Address', 'OutputValue': '10.0.0.1'}]
        self.assertEqual(stack._replace_output_placeholders('$[outputs.Address] $[outputs.Missing]'),
                         '10.0.0.1 $[outputs.Missing]')

    def test_event_and_resource_conversion(self):
        event = Event({'EventId': 'event', 'StackName': 'stack', 'LogicalResourceId': 'r',
                       'ResourceType': 'type', 'Status': 'FAILED', 'CreateTime': 'now', 'StatusReason': 'error'})
        self.assertIn('r FAILED', str(event))
        resource = Resource('stack', {'LogicalResourceId': 'r', 'ResourceType': 'type', 'Status': 'OK',
                                      'PhysicalResourceId': 'physical', 'StatusReason': 'reason'})
        self.assertEqual(resource.physical_id, 'physical')
        self.assertEqual(resource.status_reason, 'reason')
        self.assertIn('r OK', str(resource))
        timestamp = datetime(2026, 1, 1)
        updated = Resource('stack', {'LogicalResourceId': 'r', 'ResourceType': 'type', 'Status': 'OK',
                                     'UpdateTime': timestamp})
        self.assertEqual(updated.last_updated_timestamp, timestamp)

    def test_expired_refresh_and_missing_outputs_preserve_placeholders(self):
        stack = self.make_stack()
        self.assertTrue(stack._auto_refresh(datetime.now() - timedelta(days=1)))
        self.assertEqual(stack._replace_output_placeholders('$[outputs.Address]'), '$[outputs.Address]')

    async def test_refresh_collects_properties_events_and_resources(self):
        stack = self.make_stack()
        async def get_stack(stack_id, output_option):
            if output_option == 'Enabled':
                return {'Outputs': [{'OutputKey': 'A', 'OutputValue': 'B'}]}
            return {'Status': 'CREATE_COMPLETE', 'StatusReason': 'ok'}
        async def events(stack_id):
            return [{'EventId': 'e', 'StackName': 's', 'LogicalResourceId': 'r', 'ResourceType': 't',
                     'Status': 'CREATE_COMPLETE', 'CreateTime': 'now', 'StatusReason': ''}]
        async def resources(stack_id):
            return [{'LogicalResourceId': 'r', 'ResourceType': 't', 'Status': 'CREATE_COMPLETE'}]
        stack.plugin.get_stack = get_stack
        stack.plugin.list_stack_events = events
        stack.plugin.list_stack_resources = resources
        await stack.refresh(properties=True, events=True, resources=True)
        self.assertEqual(stack.status, 'CREATE_COMPLETE')
        self.assertEqual(stack.outputs[0]['OutputValue'], 'B')
        self.assertEqual((await stack.events())[0].event_id, 'e')
        self.assertEqual((await stack.resources())[0].logical_id, 'r')
        stack.timer.cancel.assert_called()
        self.assertFalse(stack._auto_refresh(datetime.now() + timedelta(days=1)))

    async def test_refresh_preserves_status_on_empty_response_and_uses_cached_details(self):
        stack = self.make_stack()
        stack.status = 'CREATE_IN_PROGRESS'
        calls = []

        async def get_stack(stack_id, output_option):
            calls.append(('properties', output_option))
            return {}

        async def events(stack_id):
            calls.append(('events', stack_id))
            return [{'EventId': 'e', 'StackName': 's', 'LogicalResourceId': 'r', 'ResourceType': 't',
                     'Status': 'CREATE_IN_PROGRESS', 'CreateTime': 'now', 'StatusReason': ''}]

        async def resources(stack_id):
            calls.append(('resources', stack_id))
            return [{'LogicalResourceId': 'r', 'ResourceType': 't', 'Status': 'CREATE_IN_PROGRESS'}]

        stack.plugin.get_stack = get_stack
        stack.plugin.list_stack_events = events
        stack.plugin.list_stack_resources = resources
        await stack.refresh(properties=True, events=True, resources=True)
        self.assertEqual(stack.status, 'CREATE_IN_PROGRESS')
        await stack.events()
        await stack.resources()
        self.assertEqual(calls, [('properties', 'Disabled'), ('events', 'stack-id'), ('resources', 'stack-id')])
        await stack.events(refresh=True)
        await stack.resources(refresh=True)
        self.assertEqual(calls[-2:], [('events', 'stack-id'), ('resources', 'stack-id')])

    async def test_delete_handles_missing_id_and_disappeared_stack(self):
        stack = self.make_stack()
        calls = []

        async def delete_stack(stack_id):
            calls.append(stack_id)
            return True

        async def missing_properties():
            return False

        stack.plugin.delete_stack = delete_stack
        stack.set_stack_properties = missing_properties
        stack.id = None
        await Stack.delete(stack)
        self.assertEqual(calls, [])
        stack.id = 'stack-id'
        await Stack.delete(stack)
        self.assertEqual(calls, ['stack-id'])
        self.assertEqual(stack.status, 'DELETE_COMPLETE')
        stack.timer.cancel.assert_called()

    async def test_delete_resumes_refresh_when_stack_is_still_deleting(self):
        stack = self.make_stack()

        async def delete_stack(stack_id):
            return True

        async def properties():
            stack.status = 'DELETE_IN_PROGRESS'
            return True

        stack.plugin.delete_stack = delete_stack
        stack.set_stack_properties = properties
        old_timer = stack.timer
        with mock.patch('iact3.stack.Timer') as timer:
            await Stack.delete(stack)
        old_timer.cancel.assert_called_once()
        timer.assert_called_once_with(stack.auto_refresh_interval.total_seconds(), stack.refresh)
        self.assertIs(stack.timer, timer.return_value)

    async def test_hook_results_append_and_missing_report_skips_execution(self):
        stack = self.make_stack()
        stack.hook_results = ['previous']
        calls = []

        async def execute(*args):
            calls.append(args)
            return 'new'

        hook = SimpleNamespace(execute_command=None, execute_time=HookExecuteTime.PRE_CREATE, execute=execute)
        stack.test_config = SimpleNamespace(hooks={'hook': hook})
        await stack.execute_hook(HookExecuteTime.PRE_CREATE, None, stack.uuid)
        self.assertEqual(stack.hook_results, ['previous'])
        self.assertEqual(calls, [])
        await stack.execute_hook(HookExecuteTime.PRE_CREATE, '/tmp/report', stack.uuid)
        self.assertEqual(stack.hook_results, ['previous', 'new'])
        self.assertEqual(hook.execute_command, [])

    async def test_hooks_ignore_empty_results_and_skip_without_test_config(self):
        stack = self.make_stack()
        await stack.execute_hook(HookExecuteTime.PRE_CREATE, '/tmp/report', stack.uuid)
        self.assertEqual(stack.hook_results, [])

        async def execute(*args):
            return None

        hook = SimpleNamespace(execute_command=[], execute_time=HookExecuteTime.PRE_CREATE, execute=execute)
        stack.test_config = SimpleNamespace(hooks={'hook': hook})
        await stack.execute_hook(HookExecuteTime.PRE_CREATE, '/tmp/report', stack.uuid)
        self.assertEqual(stack.hook_results, [])

    async def test_refresh_can_fetch_details_without_refreshing_properties(self):
        stack = self.make_stack()
        calls = []

        async def events(stack_id):
            calls.append(('events', stack_id))
            return []

        async def resources(stack_id):
            calls.append(('resources', stack_id))
            return []

        stack.plugin.list_stack_events = events
        stack.plugin.list_stack_resources = resources
        await stack.refresh(properties=False, events=True, resources=True)
        self.assertEqual(calls, [('events', 'stack-id'), ('resources', 'stack-id')])
        stack.plugin.get_stack.assert_not_called()

    async def test_property_refresh_without_stack_id_keeps_previous_status(self):
        stack = self.make_stack()
        stack.id = None
        stack.status = 'CREATE_IN_PROGRESS'
        self.assertFalse(await stack.set_stack_properties())
        self.assertEqual(stack.status, 'CREATE_IN_PROGRESS')
        stack.plugin.get_stack.assert_not_called()

    async def test_hooks_replace_outputs_and_execute_only_matching_phase(self):
        stack = self.make_stack()
        stack.outputs = [{'OutputKey': 'IP', 'OutputValue': '1.2.3.4'}]
        calls = []
        async def execute(*args):
            calls.append(args)
            return 'result'
        hook = SimpleNamespace(execute_command=['$[stack.name] $[outputs.IP]'],
                               execute_time=HookExecuteTime.PRE_CREATE, execute=execute)
        stack.test_config = SimpleNamespace(hooks={'hook': hook})
        await stack.execute_hook(HookExecuteTime.PRE_CREATE, '/tmp/report', stack.uuid)
        self.assertEqual(hook.execute_command, ['stack-name 1.2.3.4'])
        self.assertEqual(stack.hook_results, ['result'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(await Stack._execute_hook(HookExecuteTime.POST_CREATE, {'hook': hook},
                                                   '/tmp/report', 'stack', stack.uuid, 'cn-test'), [])

    async def test_stacker_rejects_price_or_preview_when_already_initialized(self):
        from iact3.exceptions import Iact3Exception
        stacker = Stacker(stacks=[self.make_stack()])
        with self.assertRaises(Iact3Exception):
            await stacker.get_stacks_price()
        with self.assertRaises(Iact3Exception):
            await stacker.preview_stacks_result()
        with self.assertRaises(Iact3Exception):
            await stacker.create_stacks()

    async def test_stacker_deletion_skips_uncreated_stack(self):
        stack = self.make_stack()
        stack.id = None
        stack.status = 'CREATE_UNCONFIRMED'
        snapshots = []
        stacker = Stacker(stacks=[stack], stack_observer=lambda: snapshots.append(stack.status))
        await stacker.delete_stacks()
        self.assertEqual(stack.status, 'CREATE_UNCONFIRMED')
        self.assertEqual(snapshots, ['CREATE_UNCONFIRMED', 'CREATE_UNCONFIRMED'])
        stack.plugin.delete_stack.assert_not_called()


class TestStackAnalysis(AsyncTestCase):
    def config(self, error=None):
        return SimpleNamespace(parameters={'A': 'value'}, template_config=SimpleNamespace(to_dict=lambda: {'template_body': 'body'}),
                               test_name='example', region='cn-test', auth=SimpleNamespace(credential=object()),
                               error=error, hooks={})

    async def test_price_and_preview_success_use_requested_parameters(self):
        from uuid import uuid4
        calls = []
        async def price(**kwargs):
            calls.append(('price', kwargs))
            return {'ECS': {'amount': 1}}
        async def preview(**kwargs):
            calls.append(('preview', kwargs))
            return [{'resource': 'ECS'}]
        plugin = mock.Mock()
        plugin.get_template_estimate_cost = price
        plugin.preview_stack = preview
        with mock.patch('iact3.stack.StackPlugin', return_value=plugin), mock.patch('iact3.stack.Timer'):
            priced = await Stack.get_price(self.config(), uuid=uuid4())
            previewed = await Stack.preview_stack_result(self.config(), uuid=uuid4())
        self.assertEqual(priced.template_price, {'ECS': {'amount': 1}})
        self.assertEqual(previewed.preview_result, [{'resource': 'ECS'}])
        self.assertEqual(calls[0][1]['parameters'], {'A': 'value'})
        self.assertEqual(calls[1][1]['region_id'], 'cn-test')

    async def test_analysis_returns_failure_status_for_config_and_service_errors(self):
        from uuid import uuid4
        from Tea.exceptions import TeaException
        from iact3.exceptions import Iact3Exception
        async def fail(**kwargs):
            raise TeaException({'code': 'Forbidden', 'message': 'denied'})
        plugin = mock.Mock()
        plugin.get_template_estimate_cost = fail
        plugin.preview_stack = fail
        with mock.patch('iact3.stack.StackPlugin', return_value=plugin), mock.patch('iact3.stack.Timer'):
            for method in (Stack.get_price, Stack.preview_stack_result):
                result = await method(self.config(), uuid=uuid4())
                self.assertEqual(result.status, 'Forbidden')
                self.assertEqual(result.status_reason, 'denied')
                self.assertFalse(result.launch_succeeded)
                result = await method(self.config(error=Iact3Exception('invalid', code='CONFIG_ERROR')), uuid=uuid4())
                self.assertEqual(result.status, 'CONFIG_ERROR')
                self.assertEqual(result.status_reason, 'invalid')
                self.assertFalse(result.launch_succeeded)

    async def test_stacker_runs_analysis_for_each_test_and_preserves_results(self):
        from iact3.stack import Stacks
        calls = []
        async def price(test, tags, uid):
            calls.append((test, dict(tags)))
            return 'price-' + test
        async def preview(test, tags, uid):
            return 'preview-' + test
        with mock.patch.object(Stack, 'get_price', price), mock.patch.object(Stack, 'preview_stack_result', preview):
            priced = Stacker(project_name='project', tests=['one', 'two'])
            await priced.get_stacks_price()
            self.assertEqual(priced.stacks, ['price-one', 'price-two'])
            self.assertEqual([call[0] for call in calls], ['one', 'two'])
            self.assertEqual(calls[0][1]['iact3-project-name'], 'project')
            previewed = Stacker(tests=['one', 'two'], stacks=Stacks())
            await previewed.preview_stacks_result()
            self.assertEqual(previewed.stacks, ['preview-one', 'preview-two'])


class TestStackCreationFailures(AsyncTestCase):
    config = TestStackAnalysis.config

    async def test_successful_create_returns_stack_and_refreshes_without_observer(self):
        from uuid import uuid4
        calls = []
        plugin = mock.Mock()

        async def create(**kwargs):
            calls.append(kwargs)
            return 'stack-id'

        async def refresh(stack):
            calls.append(stack.id)

        plugin.create_stack = create
        with mock.patch('iact3.stack.StackPlugin', return_value=plugin), mock.patch('iact3.stack.Timer'), \
             mock.patch.object(Stack, 'refresh', refresh):
            result = await Stack.create(self.config(), uuid=uuid4())
        self.assertEqual(result.id, 'stack-id')
        self.assertEqual(calls[0]['parameters'], {'A': 'value'})
        self.assertEqual(calls[1], 'stack-id')

    async def test_invalid_config_is_checkpointed_without_cloud_create(self):
        from uuid import uuid4
        from iact3.exceptions import Iact3Exception
        calls = []
        plugin = mock.Mock()
        with mock.patch('iact3.stack.StackPlugin', return_value=plugin), mock.patch('iact3.stack.Timer'):
            result = await Stack.create(self.config(Iact3Exception('invalid input', code='INVALID')), uuid=uuid4(),
                                        stack_created_callback=lambda stack: calls.append(stack.status))
        self.assertEqual(result.status, 'INVALID')
        self.assertEqual(result.status_reason, 'invalid input')
        self.assertFalse(result.launch_succeeded)
        self.assertEqual(calls, ['INVALID'])
        plugin.create_stack.assert_not_called()

    async def test_invalid_config_without_observer_does_not_start_cloud_create(self):
        from uuid import uuid4
        from iact3.exceptions import Iact3Exception
        plugin = mock.Mock()
        with mock.patch('iact3.stack.StackPlugin', return_value=plugin), mock.patch('iact3.stack.Timer'):
            result = await Stack.create(self.config(Iact3Exception('invalid', code='INVALID')), uuid=uuid4())
        self.assertEqual(result.status, 'INVALID')
        self.assertFalse(result.launch_succeeded)
        plugin.create_stack.assert_not_called()

    async def test_failed_create_and_lookup_leave_uncertain_checkpoint(self):
        from uuid import uuid4
        from Tea.exceptions import TeaException
        calls = []
        async def create(**kwargs):
            raise TeaException({'code': 'Timeout', 'message': 'request timed out'})
        async def lookup(**kwargs):
            calls.append('lookup')
            raise ValueError('lookup unavailable')
        async def sleep(delay):
            calls.append(('sleep', delay))
        plugin = mock.Mock()
        plugin.create_stack = create
        plugin.list_stacks = lookup
        statuses = []
        with mock.patch('iact3.stack.StackPlugin', return_value=plugin), mock.patch('iact3.stack.Timer'), \
             mock.patch('iact3.stack.asyncio.sleep', sleep):
            result = await Stack.create(self.config(), uuid=uuid4(),
                                        stack_created_callback=lambda stack: statuses.append(stack.status))
        self.assertEqual(result.status, 'CREATE_UNCONFIRMED')
        self.assertEqual(result.status_reason, 'request timed out')
        self.assertFalse(result.launch_succeeded)
        self.assertEqual(statuses, ['CREATE_REQUESTING', 'CREATE_UNCONFIRMED'])
        self.assertEqual(calls.count('lookup'), 3)
        self.assertEqual(calls.count(('sleep', 1)), 2)

    async def test_timeout_recovers_matching_created_stack_and_checkpoints_it(self):
        from uuid import uuid4
        from Tea.exceptions import TeaException
        statuses = []
        plugin = mock.Mock()

        async def create(**kwargs):
            self.stack_name = kwargs['stack_name']
            raise TeaException({'code': 'Timeout', 'message': 'request timed out'})

        async def lookup(**kwargs):
            return [{'StackName': 'other', 'StackId': 'wrong'},
                    {'StackName': self.stack_name},
                    {'StackName': self.stack_name, 'StackId': 'recovered'}]

        async def refresh(stack):
            statuses.append(('refresh', stack.id))

        plugin.create_stack = create
        plugin.list_stacks = lookup
        with mock.patch('iact3.stack.StackPlugin', return_value=plugin), mock.patch('iact3.stack.Timer'), \
             mock.patch.object(Stack, 'refresh', refresh):
            result = await Stack.create(self.config(), uuid=uuid4(),
                                        stack_created_callback=lambda stack: statuses.append((stack.status, stack.id)))
        self.assertEqual(result.id, 'recovered')
        self.assertEqual(result.status, 'CREATE_IN_PROGRESS')
        self.assertEqual(statuses, [('CREATE_REQUESTING', None), ('CREATE_IN_PROGRESS', 'recovered'),
                                    ('refresh', 'recovered')])


def test_filter_requires_all_criteria_to_match():
    from types import SimpleNamespace
    from iact3.stack import criteria_matches

    item = SimpleNamespace(region='cn-a', status='CREATE_COMPLETE')
    assert criteria_matches({'region': 'cn-a', 'status': 'CREATE_COMPLETE'}, item)
    assert not criteria_matches({'region': 'cn-a', 'status': 'CREATE_FAILED'}, item)
    assert not criteria_matches({'region': ['cn-b'], 'status': 'CREATE_COMPLETE'}, item)
    assert criteria_matches({'region': ['cn-a', 'cn-b'], 'status': 'CREATE_COMPLETE'}, item)
    assert criteria_matches({}, item)
