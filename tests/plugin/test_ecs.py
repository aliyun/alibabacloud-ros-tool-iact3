# -*- coding: utf-8 -*-
from iact3.plugin.ecs import EcsPlugin
from tests.common import BaseTest


class TestEcsPlugin(BaseTest):

    def setUp(self) -> None:
        super(TestEcsPlugin, self).setUp()
        self.plugin = EcsPlugin(region_id=self.REGION_ID)

    async def test_get_sg(self):
        result = await self.plugin.get_security_group(vpc_id='vpc-2zeh14fqe8g53hoyvxdpv')
        self._pprint_json(result)
