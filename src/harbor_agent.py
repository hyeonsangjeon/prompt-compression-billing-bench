"""The pinned Terminus agent with observation-only terminal instrumentation."""

from harbor.agents.terminus_2.terminus_2 import Terminus2

from .command_trace import CommandTrace
from .live_transport import TRIAL_CALL_LIMIT_ERROR
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

    async def _run_agent_loop(self, *arguments, **keywords):
        try:
            return await super()._run_agent_loop(*arguments, **keywords)
        except Exception as error:
            if (
                getattr(error, "status_code", None) != 409
                or not str(error).endswith(TRIAL_CALL_LIMIT_ERROR)
            ):
                raise
            self.logger.warning(
                "Provider call limit reached; preserving the current workspace for verification"
            )
