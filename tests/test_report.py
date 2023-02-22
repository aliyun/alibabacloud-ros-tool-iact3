import os

from iact3.report.generate_reports import ReportBuilder
from iact3.stack import Stacker
from tests.common import BaseTest


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
