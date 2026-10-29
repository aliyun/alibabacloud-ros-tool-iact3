import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from xml.dom import minidom

from iact3.report.generate_reports import ReportBuilder
from tests.common import AsyncTestCase


class TestReportBuilder(AsyncTestCase):
    async def test_failed_stack_is_reflected_in_html_and_json_report(self):
        stack = SimpleNamespace(test_name='smoke', region='cn-a', name='stack-name', id='stack-id',
                                status='CREATE_FAILED', launch_succeeded=False)
        with tempfile.TemporaryDirectory() as directory:
            builder = ReportBuilder(SimpleNamespace(project_name='demo', stacks=[stack]), Path(directory))
            html = await builder.generate_report()
            result = json.loads((Path(directory) / 'demo-result.json').read_text())
            self.assertIn('CREATE_FAILED', html)
            self.assertIn('stack-name-cn-a.txt', html)
            self.assertEqual(result['Result'], 'Failed')
            self.assertEqual(result['Details'][0]['Result'], 'Failed')
            self.assertEqual(result['Details'][0]['StackId'], 'stack-id')

    async def test_events_and_resources_include_empty_and_present_reasons(self):
        async def events(refresh):
            self.assertTrue(refresh)
            return [SimpleNamespace(timestamp='now', status='FAILED', type='t', logical_id='r', status_reason='denied'),
                    SimpleNamespace(timestamp='later', status='COMPLETE', type='t', logical_id='s', status_reason='')]

        async def resources(refresh):
            self.assertTrue(refresh)
            return [SimpleNamespace(last_updated_timestamp='now', status='FAILED', type='t', logical_id='r',
                                    physical_id='p', status_reason='denied')]

        stack = SimpleNamespace(events=events, resources=resources)
        self.assertEqual([e['ResourceStatusReason'] for e in await ReportBuilder.get_events(stack)], ['denied', ''])
        self.assertEqual((await ReportBuilder.get_resources(stack))[0]['ResourceStatusReason'], 'denied')

    async def test_xml_attributes_preserve_nested_maps_and_lists(self):
        builder = object.__new__(ReportBuilder)
        doc = minidom.Document()
        root = doc.createElement('root')
        doc.appendChild(root)
        await builder.add_attr_minidom(doc, root, 'details', {'events': [{'status': 'ok'}, {'status': 'failed'}]})
        self.assertEqual([node.firstChild.data for node in doc.getElementsByTagName('status')], ['ok', 'failed'])

    def test_missing_packaged_css_is_reported(self):
        with mock.patch('iact3.report.generate_reports.sys.frozen', True, create=True), \
             mock.patch('iact3.report.generate_reports.sys._MEIPASS', '/nonexistent/bundle', create=True):
            with self.assertRaises(FileNotFoundError):
                ReportBuilder._resolve_css_path()
