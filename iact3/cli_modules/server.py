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
        :param host: loopback address to bind, default 127.0.0.1
        :param port: port number to bind, default 8088
        :param token: access token; generated automatically when omitted
        '''
        from iact3.web.app import run_server
        if host not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError(
                'The built-in server only accepts loopback addresses. '
                'Use an SSH tunnel for remote access.'
            )
        if token is not None and (not isinstance(token, str) or not token.strip()):
            raise ValueError('The access token must not be empty')
        LOG.info(f'Starting iact3 web server at http://{host}:{port}')
        await run_server(host=host, port=port, token=token)
