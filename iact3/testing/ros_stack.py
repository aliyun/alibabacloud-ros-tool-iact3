import logging

from iact3.exceptions import InvalidActionError
from iact3.stack import Stacker
from iact3.testing.base import Base

LOG = logging.getLogger(__name__)


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
