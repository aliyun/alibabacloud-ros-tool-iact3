from unittest import mock

from iact3.config import *
from tests.common import BaseTest


class TestConfig(BaseTest):
    config_data = {
        GENERAL: {
            AUTH: {
                'name': 'my-default-profile',
                'location': '~/.aliyun/config.json'
            },
            REGIONS: ['cn-hangzhou', 'cn-shanghai'],
            PARAMETERS: {
                'Key1': 'Value1',
                'Key2': 'Value2',
                'Tags': [{'Key': 'ros', 'Value': 'xxxx'}]
            },
            TAGS: {
                'Tag1': 'value1',
                'Tag2': 'value2'
            },
            OSS_CONFIG: {
                'bucket_name': 'example-name',
                'bucket_region': 'cn-hangzhou'
            }
        },
        PROJECT: {
            NAME: 'name',
            REGIONS: ['cn-hangzhou', 'cn-beijing'],
            PARAMETERS: {
                'Key1': 'Value-new',
                'Key3': 'value3'
            },
            TAGS: {
                'Tag1': 'value-new',
                'Tag3': 'value3'
            },
            TEMPLATE_CONFIG: {
                'template_location': 'ros-template/'
            },
            ROLE_NAME: 'my-test-role'
        },
        TESTS: {
            'test1': {
                NAME: 'test',
                REGIONS: ['cn-hangzhou', 'cn-shanghai'],
                PARAMETERS: {
                    'Key1': 'Value1-base-test',
                    'Key2': 'value2-base-test'
                },
                TAGS: {
                    'Key': 'Value-base-test'
                }
            },
            'test2': {
                PARAMETERS: {
                    'Key4': 'value4'
                }
            }
        }
    }

    def test_dataclass_init(self):
        project = BaseConfig.from_dict(self.config_data)
        print(project)

    def test_create_from_default_file(self):
        with self.assertRaises(FileNotFoundError) as cm:
            BaseConfig.create()
        ex = cm.exception
        self.assertEqual(ex.errno, 2)
        self.assertEqual(True, ex.filename.endswith(f'.{IAC_NAME}.yml'))

    def test_merge(self):
        data1 = {
            PROJECT: {
                NAME: 'unit',
                REGIONS: ['cn-qingdao', 'cn-beijing'],
                PARAMETERS: {
                    'Key': 'Value-data1-project',
                    'Key1': 'Value1-data1-project'
                },
                TAGS: {
                    'Tag1': 'value1-data1-project',
                    'Tag2': 'value2-data1-project'
                },
            },
            TESTS: {
                'test1': {
                    NAME: 'unit1',
                    REGIONS: ['cn-shanghai'],
                    PARAMETERS: {
                        'Key1': 'Value1-data1-test',
                        'Key2': 'value2-data1-test'
                    },
                    TAGS: {
                        'Key': 'Value-data1-test'
                    }
                },
                'test3': {
                    NAME: 'unit3',
                    REGIONS: ['cn-shanghai', 'cn-hangzhou', 'cn-beijing'],
                }
            }
        }

        result = BaseConfig.merge(self.config_data, data1)
        self.assertEqual(result[GENERAL], self.config_data[GENERAL])
        self.assertEqual(result[PROJECT][REGIONS], data1[PROJECT][REGIONS])
        self.assertEqual(result[PROJECT][PARAMETERS]['Key1'], self.config_data[PROJECT][PARAMETERS]['Key1'])
        self.assertEqual(result[PROJECT][TAGS]['Tag1'], data1[PROJECT][TAGS]['Tag1'])
        self.assertEqual(result[TESTS]['test1'][NAME], data1[TESTS]['test1'][NAME])
        self._pprint_json(result)

    async def test_get_all_configs(self):
        global_config = os.path.join(self.DATA_PATH, 'test_global_config.yml')
        global_config_path = Path(global_config).expanduser().resolve()
        project_config = os.path.join(self.DATA_PATH, 'test_project_config.yml')
        project_config_path = Path(project_config).expanduser().resolve()
        template_path = os.path.join(self.DATA_PATH, 'simple_template.yml')
        args = {
            PROJECT: {
                REGIONS: ['cn-hangzhou', 'cn-shanghai', 'cn-beijing', 'cn-qingdao'],
                TEMPLATE_CONFIG: {
                    'template_location': template_path
                }
            }
        }
        config = BaseConfig.create(
            global_config_path=global_config_path,
            project_config_file=project_config_path,
            args=args
        )
        self._pprint_json(config.to_dict())

        with mock.patch('iact3.plugin.oss.OssPlugin.bucket_exist', return_value=True):
            configs = await config.get_all_configs()
        self.assertEqual(8, len(configs))

    def test_auth(self):
        default_auth = Auth()
        default_file = Path(DEFAULT_AUTH_FILE).expanduser().resolve()
        if default_file.is_file():
            self.assertIsInstance(default_auth.credential, CredentialClient)
        else:
            self.assertEqual(default_auth.credential, None)

        auth_name_not_exit = Auth.from_dict({'name': 'not_exist'})
        self.assertEqual(auth_name_not_exit.credential, None)

        auth_name_exit = Auth.from_dict({'name': 'test_2'})
        self.assertIsInstance(auth_name_exit.credential, CredentialClient)

    def test_get_template(self):
        template_config = TemplateConfig.from_dict({})
        tpl = self.DATA_PATH / 'not_exist'
        result = template_config._get_template_location(tpl)
        self.assertIsNone(result)

        tpl = self.DATA_PATH / 'tf'
        result = template_config._get_template_location(tpl)
        self._pprint_json(result)
