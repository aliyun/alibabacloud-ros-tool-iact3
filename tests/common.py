import json
from pathlib import Path

from iact3.logger import init_cli_logger

import asynctest


class BaseTest(asynctest.TestCase):
    REGION_ID = 'cn-shanghai'

    DATA_PATH = Path(__file__).parent / 'data'

    def setUp(self) -> None:
        init_cli_logger(loglevel='Debug')

    @staticmethod
    def _pprint_json(data, ensure_ascii=False):
        print(json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '),
                         ensure_ascii=ensure_ascii))
