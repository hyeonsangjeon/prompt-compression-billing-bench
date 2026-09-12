"""The pinned Terminus agent with observation-only terminal instrumentation."""

from harbor.agents.terminus_2.terminus_2 import Terminus2

from .command_trace import CommandTrace
from .protection import digest


class ObservedTerminus2(Terminus2):
    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        self.command_trace = CommandTrace(self.logs_dir / "command-trace")

    async def _execute_commands(self, commands, session):
        traced = self.command_trace.session(session)
        result = await super()._execute_commands(commands, traced)
        self.command_trace.append({
            "event": "batch_finished", "batch": self.command_trace.batch,
            "timed_out": result[0], "terminal_output_sha256": digest(result[1].encode()),
        })
        return result
