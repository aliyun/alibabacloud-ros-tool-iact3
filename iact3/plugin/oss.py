import base64
import json

import oss2
from alibabacloud_credentials import credentials
from retrying import retry

from iact3.plugin.base_plugin import CredentialClient


def retry_on_exception(exception):
    return isinstance(exception, oss2.exceptions.RequestError)


class OssPlugin:

    def __init__(self, region_id: str,
                 bucket_name: str,
                 endpoint: str = None,
                 credential: CredentialClient = None,
                 **kwargs):
        self.region_id = region_id
        self.auth = self._get_auth(credential)
        if not endpoint:
            endpoint = f'https://oss-{self.region_id}.aliyuncs.com'
        self.endpoint = endpoint
        self.client = oss2.Bucket(
            self.auth, self.endpoint, bucket_name,
            app_name='iact3',
            connect_timeout=30,
            **kwargs)

    def _get_auth(self, cred: CredentialClient = None):
        cred_client = CredentialClient() if cred is None else cred
        credential = cred_client.cloud_credential
        if isinstance(credential, credentials.AccessKeyCredential):
            auth = oss2.Auth(
                credential.access_key_id,
                credential.access_key_secret
            )
        elif isinstance(credential, credentials.StsCredential):
            auth = oss2.StsAuth(
                credential.access_key_id,
                credential.access_key_secret,
                credential.security_token
            )
        else:
            auth = oss2.AnonymousAuth()
        return auth

    @staticmethod
    def _encode_callback(callback_params):
        cb_str = json.dumps(callback_params).strip()
        return oss2.compat.to_string(base64.b64encode(oss2.compat.to_bytes(cb_str)))

    @retry(retry_on_exception=retry_on_exception, stop_max_attempt_number=3, wait_fixed=5)
    def put_object_with_string(self, object_name: str, strings: str,
                               callback_params: dict = None, callback_var_params: dict = None):
        params = {}
        if callback_params:
            params['x-oss-callback'] = self._encode_callback(callback_params)
        if callback_var_params:
            params['x-oss-callback-var'] = self._encode_callback(callback_var_params)
        if params:
            self.client.put_object(object_name, strings, params)
        else:
            self.client.put_object(object_name, strings)

    @retry(retry_on_exception=retry_on_exception, stop_max_attempt_number=3, wait_fixed=5)
    def put_local_file(self, object_name: str, local_file: str):
        self.client.put_object_from_file(object_name, local_file)

    @retry(retry_on_exception=retry_on_exception, stop_max_attempt_number=3, wait_fixed=5)
    def object_exists(self, object_name: str):
        return self.client.object_exists(object_name)

    @retry(retry_on_exception=retry_on_exception, stop_max_attempt_number=3, wait_fixed=5)
    def get_object_content(self, object_name: str):
        return self.client.get_object(object_name)

    @retry(retry_on_exception=retry_on_exception, stop_max_attempt_number=3, wait_fixed=5)
    def get_object_meta(self, object_name: str):
        return self.client.get_object_meta(object_name)

    @retry(retry_on_exception=retry_on_exception, stop_max_attempt_number=3, wait_fixed=5)
    def bucket_exist(self):
        try:
            self.client.get_bucket_info()
        except Exception as ex:
            if isinstance(ex, oss2.exceptions.NoSuchBucket):
                return False
            raise
        return True
