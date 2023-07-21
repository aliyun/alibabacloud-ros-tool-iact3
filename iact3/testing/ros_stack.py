import logging
import json

from iact3.exceptions import InvalidActionError
from iact3.stack import Stacker
from iact3.testing.base import Base

from typing import Any, Type, TypeVar, List

from iact3.termial_print import TerminalPrinter

LOG = logging.getLogger(__name__)

T = TypeVar("T", bound="Test")

class StackTest(Base):

    async def run(self) -> None:
        self.stacker = Stacker(
            self.project_name,
            self.configs,
            uid=self.uid
        )
        await self.stacker.create_stacks()
        await self.printer.report_test_progress(stacker=self.stacker)
        self.passed = True
        self.result = self.stacker.stacks

    async def clean_up(self) -> None:
        '''
        Deletes the Test related resources.
        '''
        if self.stacker is None:
            LOG.warning('No stacks were created... skipping cleanup.')
            return

        if self.no_delete:
            return

        if self.keep_failed:
            kwargs = {'status': ['CREATE_COMPLETE', 'UPDATE_COMPLETE']}
            await self.stacker.delete_stacks(**kwargs)
        else:
            await self.stacker.delete_stacks()

        if not self.dont_wait_for_delete:
            await self.printer.report_test_progress(stacker=self.stacker)
        status = self.stacker.status()
        if len(status.get('FAILED', {})) > 0:
            raise InvalidActionError(
                f"One or more stacks failed to create: {status['FAILED']}"
            )

    async def get_stacks_price(self) -> None:
        '''
        Get price of templates.
        '''
        self.stacker = Stacker(
            self.project_name,
            self.configs,
            uid=self.uid
        )
        await self.stacker.get_stacks_price()
        
        TerminalPrinter._display_price(stacker=self.stacker)
    
    async def preview_stacks_result(self) -> None:
        '''
        Preview resources of templates.
        '''
        self.stacker = Stacker(
            self.project_name,
            self.configs,
            uid=self.uid
        )
        await self.stacker.preview_stacks_result()
        
        TerminalPrinter._display_preview_resources(stacker=self.stacker)

