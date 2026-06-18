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
    async def start(host: str = '0.0.0.0', port: int = 8088):
        '''
        Start the web server
        :param host: host address to bind, default 0.0.0.0
        :param port: port number to bind, default 8088
        '''
        from iact3.web.app import run_server
        LOG.info(f'Starting iact3 web server at http://{host}:{port}')
        await run_server(host=host, port=port)
