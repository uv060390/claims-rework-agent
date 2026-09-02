"""LangGraph triage agent — layer 3 of the pipeline.

Graph (maps to the AGENTS.md contract):
    gather_context (prefetch, deterministic) -> agent <-> tools loop -> submit_recommendation

The agent only RECOMMENDS: its terminal act is calling submit_recommendation, whose
args are captured and validated into the shared Recommendation schema. If it never
submits (refusal, recursion limit), the fallback is route_specialist at low
confidence — non-executable and therefore guaranteed to land with a human.
"""

import json
from decimal import Decimal, InvalidOperation

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from pipeline.agent.prompts import SYSTEM_PROMPT
from pipeline.agent.tools import make_tools
from pipeline.config import ANTHROPIC_MODEL
from pipeline.schemas import Action, Recommendation, Source

FAVORABLE_ACTIONS = {Action.ADJUST_UP, Action.REPROCESS}


def default_llm():
    from langchain_anthropic import ChatAnthropic  # deferred: offline runs need no key

    return ChatAnthropic(model=ANTHROPIC_MODEL, max_tokens=1500, temperature=0)


def build_graph(llm, tools):
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: MessagesState):
        return {"messages": [llm_with_tools.invoke(state["messages"])]}

    def route(state: MessagesState):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def _gather_context(request: dict, claim: dict, unet) -> str:
    """Deterministic prefetch: what every triage needs, before any LLM step."""
    fee = unet.get(f"/fee-schedule/{claim['cpt_code']}")
    context = {
        "rework_request": request,
        "claim": claim,
        "fee_schedule_entry": fee.json() if fee.status_code == 200 else None,
    }
    if claim.get("original_claim_id"):
        original = unet.get(f"/claims/{claim['original_claim_id']}")
        context["linked_original_claim"] = original.json() if original.status_code == 200 else None
    return json.dumps(context, indent=2)


def _to_recommendation(capture: dict) -> Recommendation | None:
    if "action" not in capture:
        return None
    action = Action(capture["action"])
    amount = None
    if capture.get("adjustment_amount"):
        try:
            amount = Decimal(capture["adjustment_amount"])
        except InvalidOperation:
            return None
    if action in (Action.ADJUST_UP, Action.ADJUST_DOWN) and (amount is None or amount <= 0):
        return None  # an adjustment without a defensible amount is not actionable
    return Recommendation(
        action=action,
        adjustment_amount=amount,
        rationale=capture["rationale"],
        confidence=capture["confidence"],
        favorable_to_provider=action in FAVORABLE_ACTIONS,
        source=Source.AGENT,
    )


FALLBACK = Recommendation(
    action=Action.ROUTE_SPECIALIST,
    adjustment_amount=None,
    rationale="Agent did not produce a valid recommendation; routing to a human specialist.",
    confidence=0.2,
    favorable_to_provider=False,
    source=Source.AGENT,
)


def run_triage(
    request: dict,
    claim: dict,
    *,
    unet,
    servicenow,
    llm=None,
    max_steps: int = 16,
) -> tuple[Recommendation, list]:
    """Run the triage graph for one rework request. Returns (recommendation, messages)."""
    capture: dict = {}
    tools = make_tools(unet, servicenow, capture)
    graph = build_graph(llm or default_llm(), tools)
    messages = [
        SystemMessage(SYSTEM_PROMPT),
        HumanMessage(_gather_context(request, claim, unet)),
    ]
    try:
        result = graph.invoke({"messages": messages}, config={"recursion_limit": max_steps})
        trace = result["messages"]
    except GraphRecursionError:
        trace = messages
    return _to_recommendation(capture) or FALLBACK.model_copy(), trace
