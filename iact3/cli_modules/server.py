# -*- coding: utf-8 -*-
import logging

from iact3.cli import CliCore

LOG = logging.getLogger(__name__)


class Server:
    '''
    Start the iact3 web service for running and viewing tests.
    '''

    @staticmethod
    @CliCore.longform_param_required('host')
    @CliCore.longform_param_required('port')
    async def start(host: str = '127.0.0.1', port: int = 8088, token: str = None):
        '''
        Start the web server
        :param host: host address to bind, default 127.0.0.1 (use 0.0.0.0 for remote access)
        :param port: port number to bind, default 8088
        :param token: optional bearer token for API authentication (required when binding to non-local address)
        '''
        from iact3.web.app import run_server
        if host not in ('127.0.0.1', 'localhost', '::1') and not token:
            raise ValueError(
                'A --token is required when binding to a non-local address. '
                'Use --token to specify a bearer token for API authentication.'
            )
        LOG.info(f'Starting iact3 web server at http://{host}:{port}')
        await run_server(host=host, port=port, token=token)
