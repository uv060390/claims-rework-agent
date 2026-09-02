"""A scripted chat model: replays a fixed sequence of AI messages.

Lets tests drive the real LangGraph graph — routing, ToolNode execution, capture,
fallback — with zero network calls and no API key.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    script: list[AIMessage]
    idx: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = self.script[min(self.idx, len(self.script) - 1)]
        self.idx += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
