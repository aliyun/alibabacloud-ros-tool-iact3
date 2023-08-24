from iact3.termial_print import TerminalPrinter
from tests.common import BaseTest
from iact3.stack import Stacker
from iact3.stack import Stack

import logging
import logging.handlers

class TestConfig(BaseTest):
    async def test_display_price(self):
        template_price = {
            "KubernetesCluster":{
                "Type": "ALIYUN::CS::KubernetesCluster",
                "Result": {
                    "Order":{
                        "OriginalAmount":0,
                        "DiscountAmount":0,
                        "TradeAmount":0,
                        "Currency":""
                    },
                    "OrderSupplement": {
                        "PriceUnit": "/Hour",
                        "ChargeType": "PostPaid",
                        "Quantity": 1
                    },
                    "AssociationProducts":{
                        "SlbInstanceApiServer": {
                            "Type": "ALIYUN::SLB::LoadBalancer",
                            "Result":{
                                "Order": {
                                    "OriginalAmount": 2,
                                    "DiscountAmount": 1,
                                    "TradeAmount": 1,
                                    "Currency": ""
                                },
                                "OrderSupplement": {
                                    "PriceUnit": "/Hour",
                                    "ChargeType": "PostPaid",
                                    "Quantity": 1
                                }
                            },
                            "AssociationCU": {
                                "OrderSupplement": {
                                    "PriceUnit": "/CU",
                                    "ChargeType": "PostPaid",
                                    "Quantity": 1,
                                    "PriceType": "Unit"
                                },
                                "Result": {
                                    "Order": {
                                        "Currency": "CNY",
                                        "TradeAmount": 0.161,
                                        "OriginalAmount": 0.23,
                                        "OptionalMixPromotions": [],
                                        "DiscountAmount": 0.069
                                    },
                                    "OrderSupplement": {
                                        "PriceUnit": "/CU",
                                        "ChargeType": "PostPaid",
                                        "Quantity": 1,
                                        "PriceType": "Unit"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="",template_price=template_price)
        stacker = Stacker('test', tests=[], stacks=[stack])
        TerminalPrinter._display_price(stacker)

        logs = memory_handler.buffer

        self.assertIn("KubernetesCluster  cn-hangzhou  ALIYUN::CS::KubernetesCluster    PostPaid      /Hour                  1                          0                0              0    ", logs[3].getMessage())
        self.assertIn("ALIYUN::SLB::LoadBalancer        PostPaid      /Hour                  1                          2                1              1", logs[4].getMessage())
        self.assertIn("SLB::LoadBalancer-AssociationCU  PostPaid      /CU                    1  CNY                     0.23             0.069          0.161", logs[5].getMessage())

    async def test_display_price_with_no_template_price(self):

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="", template_price=None, status_reason="**")
        stack.status = "*"
        stacker = Stacker('test', tests=[], stacks=[stack])
        TerminalPrinter._display_price(stacker)

        logs = memory_handler.buffer
        self.assertIn("*", logs[1].getMessage())
        self.assertIn("**", logs[2].getMessage())

    async def test_display_validation(self):
        template_validation = {
            "RequestId": "***",
            "HostId": "ros.aliyuncs.com",
            "Code": "InvalidTemplate",
            "Message": "Resource [VSwitch]: The specified reference \"ZoneId\" (in unknown) is incorrect.",
            "Recommend": "https://api.aliyun.com/troubleshoot?q=InvalidTemplate&product=ROS"
        }
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        TerminalPrinter._display_validation(template_validation)
        logs = memory_handler.buffer
        self.assertEqual("validate_result    result_reason",logs[0].getMessage())
        self.assertIn("InvalidTemplate", logs[2].getMessage())

        template_validation = {

        }

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        TerminalPrinter._display_validation(template_validation)
        logs = memory_handler.buffer
        self.assertEqual("validate_result    result_reason", logs[0].getMessage())
        self.assertIn("LegalTemplate      Check passed", logs[2].getMessage())

    async def test_display_preview_resources(self):
        preview_result = [
            {
                "ResourceType": "ALIYUN::VPC::EIPAssociation",
                "LogicalResourceId": "EipBind",
                "Properties": {
                    "InstanceId": "EcsInstance",
                    "AllocationId": "EIP",
                    "InstanceType": "EcsInstance"
                }
            }
        ]
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)
        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="", preview_result=preview_result)
        stacker = Stacker('test', tests=[], stacks=[stack])
        TerminalPrinter._display_preview_resources(stacker)
        logs = memory_handler.buffer
        self.assertIn("EipBind              VPC::EIPAssociation  {", logs[4].getMessage())
        self.assertIn("\"AllocationId\": \"EIP\",", logs[5].getMessage())

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)
        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="", preview_result=None,status_reason="**")
        stack.status = "*"
        stacker = Stacker('test', tests=[], stacks=[stack])
        TerminalPrinter._display_preview_resources(stacker)
        logs = memory_handler.buffer
        self.assertIn("*", logs[2].getMessage())
        self.assertIn("**", logs[3].getMessage())

