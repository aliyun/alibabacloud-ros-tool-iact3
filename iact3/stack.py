import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from uuid import UUID, uuid4

from Tea.exceptions import TeaException

from iact3.config import TestConfig, IAC_NAME, HookExecuteTime
from iact3.exceptions import Iact3Exception
from iact3.plugin.ros import StackPlugin
from iact3.util import generate_client_token_ex
from iact3.plugin.base_plugin import CredentialClient

LOG = logging.getLogger(__name__)


class Timer:
    def __init__(self, interval, callback, *args, **kwargs):
        self._interval = interval
        self._callback = callback
        self._args = args if args is not None else []
        self._kwargs = kwargs if kwargs is not None else {}
        self._task = asyncio.create_task(self._job())

    async def _job(self):
        while True:
            try:
                await self._callback(*self._args, **self._kwargs)
            except Exception as ex:
                LOG.debug("An error occurred in callback %s: %s", self._callback.__name__, ex)
            await asyncio.sleep(self._interval)

    def cancel(self):
        self._task.cancel()


class FilterableList(list):
    def filter(self, kwargs: Optional[dict] = None):
        if not kwargs:
            return self
        f_list = FilterableList()
        for item in self:
            if criteria_matches(kwargs, item):
                f_list.append(item)
        return f_list


class Stacks(FilterableList):
    pass


class Resources(FilterableList):
    pass


class Events(FilterableList):
    pass


SYS_TAGS = {'CreatedBy': f'{IAC_NAME}'}


class Stacker:
    NULL_UUID = uuid.UUID(int=0)

    def __init__(self,
                 project_name: str = None,
                 tests: List[TestConfig] = None,
                 uid: uuid.UUID = NULL_UUID,
                 name_prefix: str = IAC_NAME,
                 tags: dict = None,
                 stacks: Stacks = None,
                 report_path: Path = None):
        self.tests = tests or []
        self.project_name = project_name
        self.stack_name_prefix = name_prefix
        self.uid = uuid.uuid4() if uid == Stacker.NULL_UUID else uid
        self.tags = tags if tags else {}
        self.stacks: Stacks = stacks or Stacks()
        self._sys_tags = {
            f'{IAC_NAME}-id': self.uid.hex,
            f'{IAC_NAME}-project-name': self.project_name,
        }
        self._sys_tags.update(SYS_TAGS)
        self.report_path = report_path

    @classmethod
    def from_stacks(cls, stacks: Stacks):
        return cls(stacks=stacks)

    async def create_stacks(self):
        if self.stacks:
            raise Iact3Exception('Stacker already initialised with stack objects')
        self.tags.update(self._sys_tags)
        stack_tasks = [
            asyncio.create_task(Stack.create(test, self.tags, self.uid, self.report_path)) for test in self.tests
        ]
        self.stacks += await asyncio.gather(*stack_tasks)

    def status(self, **kwargs):
        stacks = self.stacks.filter(kwargs)
        result = {}
        for stack in stacks:
            status = stack.status
            result[StackStatus.curt(status)] = {stack.id: stack.status_reason}
        return result

    async def delete_stacks(self, stacks: Stacks=None):
        if stacks is None:
            stacks = self.stacks
        await self.execute_hooks(execute_time=HookExecuteTime.PRE_DELETE, stacks=stacks)
        stack_tasks = [
            asyncio.create_task(Stack.delete(stack)) for stack in stacks
        ]
        await asyncio.gather(*stack_tasks)
    
    async def get_stacks_price(self):
        if self.stacks:
            raise Iact3Exception('Stacker already initialised with stack objects')
        self.tags.update(self._sys_tags)
        stack_tasks = [
            asyncio.create_task(Stack.get_price(test, self.tags, self.uid)) for test in self.tests
        ]
        self.stacks += await asyncio.gather(*stack_tasks)

    async def preview_stacks_result(self):
        if self.stacks:
            raise Iact3Exception('Stacker already initialised with stack objects')
        self.tags.update(self._sys_tags)
        stack_tasks = [
            asyncio.create_task(Stack.preview_stack_result(test, self.tags, self.uid)) for test in self.tests
        ]
        self.stacks += await asyncio.gather(*stack_tasks)

    async def get_stack_outputs(self):
        return [stack.get_stack_outputs() for stack in self.stacks]

    async def execute_hooks(self, execute_time, stacks: Stacks=None):
        exec_stacks = self.stacks if stacks is None else stacks
        hook_tasks = [
            asyncio.create_task(stack.execute_hook(
                execute_time=execute_time,
                report_path=self.report_path,
                uid=self.uid
            )) for stack in [s for s in exec_stacks if s.id is not None]
        ]
        return await asyncio.gather(*hook_tasks)


def criteria_matches(kwargs: dict, instance):
    for k in kwargs:
        if not hasattr(instance, k):
            raise ValueError(f'{k} is not a valid property of {type(instance)}')
    for k, v in kwargs.items():
        ins_v = getattr(instance, k)
        if isinstance(v, list):
            return ins_v in v
        return ins_v == v
    return True


class StackStatus:
    COMPLETE = [
        'CREATE_COMPLETE',
        'UPDATE_COMPLETE',
        'DELETE_COMPLETE'
    ]
    IN_PROGRESS = [
        'CREATE_IN_PROGRESS',
        'UPDATE_IN_PROGRESS',
        'DELETE_IN_PROGRESS',
        'CREATE_ROLLBACK_IN_PROGRESS',
        'ROLLBACK_IN_PROGRESS'
    ]
    FAILED = [
        'CREATE_FAILED',
        'UPDATE_FAILED',
        'DELETE_FAILED',
        'CREATE_ROLLBACK_FAILED',
        'CREATE_ROLLBACK_COMPLETE',
        'ROLLBACK_FAILED',
        'ROLLBACK_COMPLETE'
    ]

    @classmethod
    def curt(cls, status):
        if status in cls.COMPLETE:
            return 'COMPLETE'
        elif status in cls.IN_PROGRESS:
            return 'IN_PROGRESS'
        elif status in cls.FAILED:
            return 'FAILED'
        else:
            return 'UNKNOWN'


class Event:
    def __init__(self, event_dict: dict):
        self.event_id: str = event_dict['EventId']
        self.stack_name: str = event_dict['StackName']
        self.logical_id: str = event_dict['LogicalResourceId']
        self.type: str = event_dict['ResourceType']
        self.status: str = event_dict['Status']
        self.timestamp: str = event_dict['CreateTime']
        self.physical_id: str = event_dict.get('PhysicalResourceId')
        self.status_reason: str = event_dict['StatusReason']

    def __str__(self):
        return '{} {} {}'.format(self.timestamp, self.logical_id, self.status)

    def __repr__(self):
        return '<Event object {} at {}>'.format(self.event_id, hex(id(self)))


class Resource:
    def __init__(
            self, stack_id: str, resource_dict: dict, test_name: str = '', uuid: UUID = None
    ):
        uuid = uuid if uuid else uuid4()
        self.stack_id: str = stack_id
        self.test_name: str = test_name
        self.uuid: UUID = uuid
        self.logical_id: str = resource_dict['LogicalResourceId']
        self.type: str = resource_dict['ResourceType']
        # self.status: str = resource_dict['ResourceStatus']
        self.status: str = resource_dict['Status']
        self.physical_id: str = ''
        self.last_updated_timestamp: datetime = datetime.fromtimestamp(0)
        self.status_reason: str = ''
        if 'PhysicalResourceId' in resource_dict.keys():
            self.physical_id = resource_dict['PhysicalResourceId']
        if 'UpdateTime' in resource_dict.keys():
            self.last_updated_timestamp = resource_dict['UpdateTime']
        if 'StatusReason' in resource_dict.keys():
            self.status_reason = resource_dict['StatusReason']

    def __str__(self):
        return '<Resource {} {}>'.format(self.logical_id, self.status)


class Stack:

    def __init__(self, region: str, stack_id: Optional[str], test_name: str = None,
                 uuid: UUID = None, status_reason: str = None, stack_name: str = None,
                 parameters: dict = None, credential: CredentialClient = None, 
                 template_price: dict = None, preview_result: dict = None,
                 test_config: TestConfig = None, hook_results: list = None):
        self.test_name: str = test_name
        self.uuid: UUID = uuid if uuid else uuid4()
        self.id: str = stack_id
        self.region = region
        self.plugin: StackPlugin = StackPlugin(region_id=region, credential=credential)
        self.name = stack_name
        self.parameters = parameters
        self.completion_time: timedelta = timedelta(0)

        self._status: str = ''
        self.status_reason: str = status_reason or ''
        self._launch_succeeded: bool = False
        self.auto_refresh_interval: timedelta = timedelta(seconds=5)
        self._last_event_refresh: datetime = datetime.fromtimestamp(0)
        self._last_resource_refresh: datetime = datetime.fromtimestamp(0)
        self.timer = Timer(self.auto_refresh_interval.total_seconds(), self.refresh)
        self.template_price = template_price
        self.preview_result = preview_result
        self.outputs = None
        self.test_config = test_config
        self.hook_results = hook_results or []

    def __str__(self):
        return self.id

    def __repr__(self):
        return '<Stack object {} at {}>'.format(self.test_name, hex(id(self)))

    def _auto_refresh(self, last_refresh):
        if datetime.now() - last_refresh > self.auto_refresh_interval:
            return True
        return False

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, status):
        _complete = StackStatus.COMPLETE.copy()
        del _complete[_complete.index('DELETE_COMPLETE')]
        self._status = status
        if status in StackStatus.FAILED:
            self._launch_succeeded = False
            return
        if status in _complete:
            self._launch_succeeded = True
            return

    @property
    def launch_succeeded(self):
        return self._launch_succeeded

    @classmethod
    def from_stack_response(cls, stack: dict, credential: CredentialClient = None):
        return cls(
            region=stack['RegionId'],
            stack_id=stack['StackId'],
            test_name=stack.get('TestName'),
            uuid=stack.get('TestId'),
            stack_name=stack.get('StackName'),
            credential=credential
        )

    def _replace_output_placeholders(self, text):
        if self.outputs is None:
            return text

        outputs = {o['OutputKey']: o['OutputValue'] for o in self.outputs}
        def replace_match(match):
            key = match.group(1)
            return str(outputs.get(key, f"$[outputs.{key}]"))

        pattern = r'\$\[outputs\.([^\]]+)\]'
        return re.sub(pattern, replace_match, text)

    @staticmethod
    def _replace_stack_placeholders(text, stack_name, region):
        result = text
        if "$[stack.region]" in text:
            result = text.replace("$[stack.region]", region)

        if "$[stack.name]" in text:
            result = text.replace("$[stack.name]", stack_name)
        return result

    async def execute_hook(self, execute_time, report_path, uid):
        if self.test_config is None:
            return

        hook_config = self.test_config.hooks
        for config in hook_config.values():
            execute_command = config.execute_command or []
            config.execute_command = [self._replace_output_placeholders(c) for c in execute_command]

        results = await self._execute_hook(
            execute_time=execute_time,
            hook_config=self.test_config.hooks,
            report_path=report_path,
            stack_name=self.name,
            uid=uid,
            region=self.region
        )
        if not results:
            return
        if not self.hook_results:
            self.hook_results = results
        else:
            self.hook_results.extend(results)

    @classmethod
    async def _execute_hook(cls, execute_time, hook_config, report_path, stack_name, uid: UUID, region):
        if not hook_config or not report_path:
            return []
        results = []
        for name, config in hook_config.items():
            execute_command = config.execute_command or []
            config.execute_command = [cls._replace_stack_placeholders(c, stack_name, region) for c in execute_command]
            if config.execute_time != execute_time:
                continue
            result = await config.execute(report_path, stack_name, uid)
            if result:
                results.append(result)
        return results

    @classmethod
    async def create(cls, test: TestConfig, tags: dict = None, uuid: UUID = None,
                     report_path: Path = None) -> 'Stack':
        parameters = test.parameters
        template_args = test.template_config.to_dict()
        name = test.test_name
        if not tags:
            tags = {}
        tags.update({f'{IAC_NAME}-test-name': name})
        region = test.region
        credential = test.auth.credential
        plugin = StackPlugin(region_id=test.region, credential=credential)
        client_token = generate_client_token_ex(uuid.hex, name)
        stack_name = f'{IAC_NAME}-{name}-{region}-{uuid4().hex[:8]}'
        config_error = test.error
        if config_error:
            stack = cls(region, None, name, uuid,
                        status_reason=getattr(config_error, 'message', 'Unknown error'),
                        stack_name=stack_name, credential=credential)
            stack.status = getattr(config_error, 'code', 'Unknown error')
            stack._launch_succeeded = False
            stack.timer.cancel()
            return stack

        hook_results = await cls._execute_hook(
            HookExecuteTime.PRE_CREATE, test.hooks, report_path, stack_name, uid=uuid, region=region)
        try:
            stack_id = await plugin.create_stack(
                stack_name=stack_name,
                parameters=parameters,
                timeout_in_minutes=60,
                client_token=client_token,
                tags=tags,
                **template_args,
                disable_rollback=True
            )
        except TeaException as ex:
            stack_id = None
            stack = cls(region, stack_id, name, uuid, status_reason=ex.message,
                        stack_name=stack_name, parameters=parameters, credential=credential,
                        test_config=test, hook_results=hook_results)
            stack.status = ex.code
            stack._launch_succeeded = False
            stack.timer.cancel()
            return stack
        stack = cls(region, stack_id, name, uuid, stack_name=stack_name,
                    parameters=parameters, credential=credential,
                    test_config=test, hook_results=hook_results)
        await stack.refresh()
        return stack

    @classmethod
    async def get_price(cls, test: TestConfig, tags: dict = None, uuid: UUID = None):
        parameters = test.parameters
        template_args = test.template_config.to_dict()
        name = test.test_name
        if not tags:
            tags = {}
        tags.update({f'{IAC_NAME}-test-name': name})
        region = test.region
        credential = test.auth.credential
        plugin = StackPlugin(region_id=test.region, credential=credential)
        stack_name = f'{IAC_NAME}-{name}-{region}-{uuid4().hex[:8]}'
        config_error = test.error
        if config_error:
            stack = cls(region, None, name, uuid,
                        status_reason=getattr(config_error, 'message', 'Unknown error'),
                        stack_name=stack_name, credential=credential)
            stack.status = getattr(config_error, 'code', 'Unknown error')
            stack._launch_succeeded = False
            stack.timer.cancel()
            return stack
        try:
            template_price = await plugin.get_template_estimate_cost(
                parameters=parameters,
                **template_args,
                region_id=region
            )
        except TeaException as ex:
            stack_id = None
            stack = cls(region, stack_id, name, uuid, status_reason=ex.message,
                        stack_name=stack_name, parameters=parameters, credential=credential)
            stack.status = ex.code
            stack._launch_succeeded = False
            stack.timer.cancel()
            return stack
        stack_id = None
        stack = cls(region, stack_id, name, uuid, stack_name=stack_name,
                    parameters=parameters, credential=credential, template_price=template_price)
        return stack
    
    @classmethod
    async def preview_stack_result(cls, test: TestConfig, tags: dict = None, uuid: UUID = None):
        parameters = test.parameters
        template_args = test.template_config.to_dict()
        name = test.test_name
        if not tags:
            tags = {}
        tags.update({f'{IAC_NAME}-test-name': name})
        region = test.region
        credential = test.auth.credential
        plugin = StackPlugin(region_id=test.region, credential=credential)
        stack_name = f'{IAC_NAME}-{name}-{region}-{uuid4().hex[:8]}'
        config_error = test.error
        if config_error:
            stack = cls(region, None, name, uuid,
                        status_reason=getattr(config_error, 'message', 'Unknown error'),
                        stack_name=stack_name, credential=credential)
            stack.status = getattr(config_error, 'code', 'Unknown error')
            stack._launch_succeeded = False
            stack.timer.cancel()
            return stack
        try:
            preview_result = await plugin.preview_stack(
                parameters=parameters,
                **template_args,
                region_id=region,
                stack_name=stack_name
            )
        except TeaException as ex:
            stack_id = None
            stack = cls(region, stack_id, name, uuid, status_reason=ex.message,
                        stack_name=stack_name, parameters=parameters, credential=credential)
            stack.status = ex.code
            stack._launch_succeeded = False
            stack.timer.cancel()
            return stack
        stack_id = None
        stack = cls(region, stack_id, name, uuid, stack_name=stack_name,
                    parameters=parameters, credential=credential, preview_result=preview_result)
        return stack

    async def refresh(self, properties: bool = True, events: bool = False, resources: bool = False) -> None:
        if properties:
            await self.set_stack_properties()
        if events:
            await self._fetch_stack_events()
            self._last_event_refresh = datetime.now()
        if resources:
            await self._fetch_stack_resources()
            self._last_resource_refresh = datetime.now()

    async def set_stack_properties(self, stack_properties: Optional[dict] = None) -> None:
        props: dict = stack_properties if stack_properties else {}
        if not props:
            if self.id:
                props = await self.plugin.get_stack(self.id, output_option='Disabled') or {}
        self.status = props.get('Status')
        self.status_reason = props.get('StatusReason')

        outputs_status = ('CREATE_COMPLETE', 'UPDATE_COMPLETE', 'CREATE_FAILED', 'UPDATE_FAILED')
        if self.status in outputs_status and self.outputs is None:
            ret = await self.plugin.get_stack(self.id, output_option='Enabled')
            self.outputs = ret.get('Outputs') or []

        if self.status not in StackStatus.IN_PROGRESS:
            self.timer.cancel()

    async def events(self, refresh: bool = False) -> Events:
        if refresh or not self._events or self._auto_refresh(self._last_event_refresh):
            await self._fetch_stack_events()
        return self._events

    async def _fetch_stack_events(self) -> None:
        self._last_event_refresh = datetime.now()
        events = Events()
        stack_events = await self.plugin.list_stack_events(self.id)
        for event in stack_events:
            events.append(Event(event))
        self._events = events

    async def resources(self, refresh: bool = False) -> Resources:
        if (
                refresh
                or not self._resources
                or self._auto_refresh(self._last_resource_refresh)
        ):
            await self._fetch_stack_resources()
        return self._resources

    async def _fetch_stack_resources(self) -> None:
        self._last_resource_refresh = datetime.now()
        resources = Resources()
        stack_resources = await self.plugin.list_stack_resources(self.id)
        for res in stack_resources:
            resources.append(Resource(self.id,res,self.test_name,self.uuid))
        self._resources = resources

    @staticmethod
    async def delete(stack) -> None:
        stack_id = stack.id
        if not stack_id:
            return
        await stack.plugin.delete_stack(stack_id=stack_id)
        LOG.info(f'Deleting stack: {stack_id}')
        await stack.refresh()
        stack.timer = Timer(stack.auto_refresh_interval.total_seconds(), stack.refresh)

    def error_events(self, refresh=False) -> Events:
        errors = Events()
        stacks = Stacks([self])
        for stack in stacks:
            for status in StackStatus.FAILED:
                errors += stack.events(refresh=refresh).filter({'status': status})
        return errors
