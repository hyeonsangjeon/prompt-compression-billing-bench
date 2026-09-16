"""The pinned Terminus agent with observation-only terminal instrumentation."""

import httpx
from harbor.llms.lite_llm import LiteLLM

from harbor.agents.terminus_2.terminus_2 import Terminus2

from .command_trace import CommandTrace
from .protection import digest


class ObservedTerminus2(Terminus2):
    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        if not isinstance(self._llm, LiteLLM):
            raise RuntimeError("The pinned Terminus agent did not create LiteLLM")
        self._llm._llm_kwargs["timeout"] = httpx.Timeout(None)
        self.command_trace = CommandTrace(self.logs_dir / "command-trace")

    async def _execute_commands(self, commands, session):
        traced = self.command_trace.session(session)
        try:
            result = await super()._execute_commands(commands, traced)
        except RuntimeError as error:
            if await session.is_session_alive() is not False:
                raise
            self.command_trace.append({
                "event": "batch_finished", "batch": self.command_trace.batch,
                "terminal_session_ended": True, "error_type": type(error).__name__,
            })
            self.logger.warning(
                "Terminal session ended; preserving the current workspace for verification"
            )
            return False, ""
        self.command_trace.append({
            "event": "batch_finished", "batch": self.command_trace.batch,
            "timed_out": result[0], "terminal_output_sha256": digest(result[1].encode()),
        })
        return result
