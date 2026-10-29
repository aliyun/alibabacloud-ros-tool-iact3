import base64
import json
from types import SimpleNamespace
from unittest import mock

import oss2
import pytest
from alibabacloud_credentials.credentials import AccessKeyCredential, StsCredential

from iact3.plugin.oss import OssPlugin, retry_on_exception


def test_oss_auth_selects_credential_type():
    ak = SimpleNamespace(cloud_credential=AccessKeyCredential('id', 'secret'))
    sts = SimpleNamespace(cloud_credential=StsCredential('id', 'secret', 'token'))
    other = SimpleNamespace(cloud_credential=None)
    assert isinstance(OssPlugin._get_auth(ak), oss2.Auth)
    assert isinstance(OssPlugin._get_auth(sts), oss2.StsAuth)
    assert isinstance(OssPlugin._get_auth(other), oss2.AnonymousAuth)


def test_oss_object_operations_and_callback_encoding():
    bucket = mock.Mock()
    with mock.patch('iact3.plugin.oss.oss2.Bucket', return_value=bucket) as factory:
        plugin = OssPlugin('cn-test', 'bucket', credential=SimpleNamespace(cloud_credential=None))
    assert factory.call_args[0][1] == 'https://oss-cn-test.aliyuncs.com'
    plugin.put_object_with_string('plain', 'data')
    bucket.put_object.assert_called_with('plain', 'data')
    plugin.put_object_with_string('callback', 'data', {'url': 'https://example.invalid'}, {'key': 'value'})
    params = bucket.put_object.call_args[0][2]
    assert json.loads(base64.b64decode(params['x-oss-callback'])) == {'url': 'https://example.invalid'}
    assert json.loads(base64.b64decode(params['x-oss-callback-var'])) == {'key': 'value'}
    plugin.put_local_file('remote', 'local')
    bucket.put_object_from_file.assert_called_once_with('remote', 'local')
    plugin.object_exists('key')
    bucket.object_exists.assert_called_once_with('key')
    plugin.get_object_content('key')
    bucket.get_object.assert_called_once_with('key')
    plugin.get_object_meta('key')
    bucket.get_object_meta.assert_called_once_with('key')


def test_bucket_existence_and_error_handling():
    with mock.patch('iact3.plugin.oss.oss2.Bucket') as factory:
        plugin = OssPlugin('cn-test', 'bucket', credential=SimpleNamespace(cloud_credential=None))
        bucket = factory.return_value
        assert plugin.bucket_exist() is True
        bucket.get_bucket_info.side_effect = oss2.exceptions.NoSuchBucket(404, {}, '', {})
        assert plugin.bucket_exist() is False
        bucket.get_bucket_info.side_effect = ValueError('failure')
        with pytest.raises(ValueError):
            plugin.bucket_exist()
    assert not retry_on_exception(ValueError('failure'))
