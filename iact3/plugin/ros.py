import json

from Tea.exceptions import TeaException
from alibabacloud_ros20190910.client import Client as ROSClient

from iact3.plugin.base_plugin import TeaSDKPlugin


class ROSPlugin(TeaSDKPlugin):

    product = 'ROS'

    def api_client(self):
        return ROSClient

    def models_path(self, action_name):
        return 'alibabacloud_ros20190910.models.{}'.format(action_name)

    def runtime_kwargs(self):
        return {
            'autoretry': True,
            'max_attempts': 3,
            'read_timeout': 60000,
            'connect_timeout': 60000
        }


class StackPlugin(ROSPlugin):
    
    IGNORE_ERRORS = ('StackNotFound',)
    
    @staticmethod
    def _convert_parameters(parameters: dict, kwargs: dict):
        if not parameters:
            return
        assert isinstance(parameters, dict)

        json_dumps_param = {}
        for k, v in parameters.items():
            json_dumps_param[k] = json.dumps(v) if isinstance(v, (list, dict)) else v

        kwargs['Parameters'] = [dict(ParameterKey=k, ParameterValue=v) for k, v in json_dumps_param.items()
                                if v is not None]

    @staticmethod
    def _convert_notification_urls(notification_urls, kwargs):
        if not notification_urls:
            return
        assert isinstance(notification_urls, list)
        kwargs['NotificationUrls'] = notification_urls

    async def create_stack(self, stack_name: str, template_body: str = None,
                           parameters: dict = None, timeout_in_minutes: int = None,
                           client_token=None, disable_rollback=None,
                           stack_policy_url=None, stack_policy_body=None,
                           notification_urls=None, deletion_protection=None,
                           create_option=None, tags=None,
                           ram_role_name=None, template_id=None,
                           template_version=None, resource_group_id=None,
                           template_url=None):
        kwargs = dict(
            StackName=stack_name,
            TemplateBody=template_body,
            TimeoutInMinutes=timeout_in_minutes,
            ClientToken=client_token,
            DisableRollback=disable_rollback,
            StackPolicyURL=stack_policy_url,
            StackPolicyBody=stack_policy_body,
            NotificationURLs=notification_urls,
            DeletionProtection=deletion_protection,
            CreateOption=create_option,
            RamRoleName=ram_role_name,
            TemplateId=template_id,
            TemplateVersion=template_version,
            ResourceGroupId=resource_group_id,
            TemplateURL=template_url
        )
        self._convert_parameters(parameters, kwargs)
        self._convert_notification_urls(notification_urls, kwargs)
        self._convert_tags(tags, kwargs)
        result = await self.send_request('CreateStackRequest', **kwargs)
        return result['StackId']

    async def delete_stack(self, stack_id, retain_all_resources=None):
        kwargs = dict(
            StackId=stack_id,
            RetainAllResources=retain_all_resources
        )
        try:
            return await self.send_request('DeleteStackRequest', **kwargs)
        except TeaException as ex:
            if ex.code not in self.IGNORE_ERRORS:
                raise

    async def get_stack(self, stack_id, client_token=None, output_option=None):
        kwargs = dict(
            StackId=stack_id,
            ClientToken=client_token,
            OutputOption=output_option,
        )
        try:
            return await self.send_request('GetStackRequest', **kwargs)
        except TeaException as ex:
            if ex.code not in self.IGNORE_ERRORS:
                raise

    async def list_stacks(self, stack_id=None, stack_name=None):
        request_kwargs = dict(
            StackId=stack_id,
            StackName=[stack_name] if stack_name else None
        )
        result = await self.send_request('ListStacksRequest', **request_kwargs)
        return result.get('Stacks')

    async def fetch_all_stacks(self, tags, stack_id=None):
        kwargs = {'StackId': stack_id}
        self._convert_tags(tags, kwargs, tag_key='Tag')
        return await self.fetch_all('ListStacksRequest', kwargs, 'Stacks')

    async def list_stack_resources(self, stack_id):
        kwargs = dict(
            StackId=stack_id
        )
        result = await self.send_request('ListStackResourcesRequest', **kwargs)
        return result.get('Resources')

    async def get_stack_resource(self, stack_id, logical_resource_id, show_resource_attributes=False,
                                 resource_attributes=None):
        kwargs = dict(
            StackId=stack_id,
            LogicalResourceId=logical_resource_id
        )
        if show_resource_attributes:
            kwargs.update(
                ShowResourceAttributes='true'
            )
        elif resource_attributes:
            kwargs.update(
                ResourceAttributes=resource_attributes,
            )
        return await self.send_request('GetStackResourceRequest', **kwargs)

    async def list_stack_events(self, stack_id):
        kwargs = dict(
            StackId=stack_id
        )
        return await self.fetch_all('ListStackEventsRequest', kwargs, 'Events')

    async def get_regions(self) -> list:
        response = await self.send_request('DescribeRegionsRequest')
        return [region['RegionId'] for region in response['Regions'] or []]

    async def get_parameter_constraints(self, template_body: str = None,
                                        template_url: str = None, template_id: str = None,
                                        template_version: str = None, parameters_key_filter: list = None,
                                        parameters: dict = None, parameters_order: list = None,
                                        client_token: str = None):
        kwargs = dict(
            TemplateBody=template_body,
            TemplateURL=template_url,
            TemplateId=template_id,
            TemplateVersion=template_version,
            ParametersKeyFilter=parameters_key_filter,
            ParametersOrder=parameters_order,
            ClientToken=client_token
        )
        self._convert_parameters(parameters, kwargs)
        result = await self.send_request('GetTemplateParameterConstraints', **kwargs)
        return result['ParameterConstraints']

    async def get_template(self, template_id: str, template_version: str = None):
        kwargs = dict(
            TemplateId=template_id,
            TemplateVersion=template_version
        )
        return await self.send_request('GetTemplate', **kwargs)
    
    async def get_template_estimate_cost(self, template_body: str = None,
                           parameters: dict = None, region_id: str = None,
                           template_url: str = None):
        kwargs = dict(
            TemplateBody=template_body,
            TemplateURL=template_url,
            RegionId=region_id
        )
        self._convert_parameters(parameters, kwargs)
        result = await self.send_request('GetTemplateEstimateCostRequest', **kwargs)
        return result['Resources']
    
    async def validate_template(self, template_body: str = None,
                                region_id: str = None, template_url: str = None):
        kwargs = dict(
            TemplateBody=template_body,
            TemplateURL=template_url,
            RegionId=region_id
        )
        result = await self.send_request('ValidateTemplateRequest', ignoreException=True, **kwargs)
        return result
    
    async def preview_stack(self, template_body: str = None,
                           parameters: dict = None, region_id: str = None,
                           template_url: str = None, stack_name: str = None):
        kwargs = dict(
            TemplateBody=template_body,
            TemplateURL=template_url,
            RegionId=region_id,
            StackName=stack_name
        )
        self._convert_parameters(parameters, kwargs)
        result = await self.send_request('PreviewStackRequest', **kwargs)
        return result['Stack']['Resources']
    
    async def generate_template_policy(self, template_body: str = None, template_url: str = None):
        kwargs = dict(
            TemplateBody=template_body,
            TemplateURL=template_url
        )
        result = await self.send_request('GenerateTemplatePolicyRequest', ignoreException=True, **kwargs)
        return result['Policy']