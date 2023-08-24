import os

from iact3.report.generate_reports import ReportBuilder
from iact3.stack import Stacker
from tests.common import BaseTest
from iact3.stack import Stack


class TestReport(BaseTest):

    async def test_index(self):
        stacker = Stacker('test', tests=[])
        report = ReportBuilder(stacker, self.DATA_PATH)
        index_path = self.DATA_PATH / 'index.html'
        try:
            os.remove(index_path)
        except FileNotFoundError:
            pass
        self.assertEqual(os.path.exists(index_path), False)
        await report.generate_report()
        self.assertEqual(os.path.exists(index_path), True)

    async def test_report_default(self):
        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="")
        stacker = Stacker('test', tests=[], stacks=[stack])
        report = ReportBuilder(stacker, self.DATA_PATH)
        try:
            os.remove(self.DATA_PATH / "test-stack-cn-hangzhou.txt")
        except FileNotFoundError:
            pass
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.txt"), False)

        report_name = await report.create_logs(log_format=None)

        self.assertListEqual(report_name,["test-stack-cn-hangzhou.txt","test-result.json"])
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.txt"), True)
        with open(self.DATA_PATH / "test-stack-cn-hangzhou.txt", "r") as f:
            lines = f.readlines()


        self.assertIn("Region: cn-hangzhou\n",lines)
        self.assertIn("StackName: test-stack\n", lines)
        self.assertIn("StackId: \n", lines)
        self.assertIn("TestedResult: Failed  \n", lines)
        self.assertIn("ResultReason:  \n", lines)
        self.assertIn("Events:  \n", lines)
        self.assertIn("Resources:  \n", lines)

        for file in report_name:
            try:
                os.remove(self.DATA_PATH / file)
            except FileNotFoundError:
                pass

    async def test_report_json(self):
        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="")
        stacker = Stacker('test', tests=[], stacks=[stack])
        report = ReportBuilder(stacker, self.DATA_PATH)
        try:
            os.remove(self.DATA_PATH / "test-stack-cn-hangzhou.json")
        except FileNotFoundError:
            pass
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.json"), False)

        report_name = await report.create_logs("json")

        self.assertListEqual(report_name,["test-stack-cn-hangzhou.txt","test-stack-cn-hangzhou.json","test-result.json"])
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.json"), True)

        for file in report_name:
            try:
                os.remove(self.DATA_PATH / file)
            except FileNotFoundError:
                pass

    async def test_report_xml(self):
        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="")
        stacker = Stacker('test', tests=[], stacks=[stack])
        report = ReportBuilder(stacker, self.DATA_PATH)
        try:
            os.remove(self.DATA_PATH / "test-stack-cn-hangzhou.xml")
        except FileNotFoundError:
            pass
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.xml"), False)

        report_name = await report.create_logs("xml")

        self.assertListEqual(report_name,["test-stack-cn-hangzhou.txt","test-stack-cn-hangzhou.xml","test-result.json"])
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.xml"), True)

        for file in report_name:
            try:
                os.remove(self.DATA_PATH / file)
            except FileNotFoundError:
                pass

    async def test_report_json_xml(self):
        stack = Stack(stack_name="test-stack", region="cn-hangzhou", stack_id="")
        stacker = Stacker('test', tests=[], stacks=[stack])
        report = ReportBuilder(stacker, self.DATA_PATH)
        try:
            os.remove(self.DATA_PATH / "test-stack-cn-hangzhou.xml")
            os.remove(self.DATA_PATH / "test-stack-cn-hangzhou.json")
        except FileNotFoundError:
            pass
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.xml"), False)
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.json"), False)

        report_name = await report.create_logs("xml,json")

        self.assertListEqual(report_name,["test-stack-cn-hangzhou.txt","test-stack-cn-hangzhou.json","test-stack-cn-hangzhou.xml","test-result.json"])
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.xml"), True)
        self.assertEqual(os.path.exists(self.DATA_PATH / "test-stack-cn-hangzhou.json"), True)

        for file in report_name:
            try:
                os.remove(self.DATA_PATH / file)
            except FileNotFoundError:
                pass