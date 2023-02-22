from pathlib import Path

from iact3.config import DEFAULT_OUTPUT_DIRECTORY
from iact3.generate_params import IAC_NAME
from iact3.plugin.oss import OssPlugin
from tests.common import BaseTest


class TestOssPlugin(BaseTest):

    def setUp(self) -> None:
        super(TestOssPlugin, self).setUp()
        self.plugin = OssPlugin(region_id=self.REGION_ID, bucket_name='iact3-beijing')

    def test_put_file(self):
        report_path = Path(f'../{DEFAULT_OUTPUT_DIRECTORY}')
        for path in report_path.glob(f'{IAC_NAME}*.txt'):
            self.plugin.put_local_file(f'local_file_test/{IAC_NAME}/{path.name}', path.resolve())

    def test_exist(self):
        self.plugin.object_exists('')

