"""Read-only tools for the triage agent, plus the submit_recommendation terminator.

Every investigative tool is a GET against a mock service — the agent has no tool
that mutates a claim, releases a job, or approves anything (AGENTS.md contract).
The recommendation is captured through a closure, not returned as free text.
"""

from langchain_core.tools import BaseTool, tool

from pipeline.schemas import Action

READ_ONLY_TOOL_NAMES = {
    "get_claim",
    "get_provider_history",
    "fee_schedule_lookup",
    "get_prior_rework",
}


def make_tools(unet, servicenow, capture: dict) -> list[BaseTool]:
    """`unet`/`servicenow` are httpx-compatible clients; `capture` receives the
    submitted recommendation args."""

    @tool
    def get_claim(claim_id: str) -> dict:
        """Fetch a claim record from the claims platform by claim id."""
        resp = unet.get(f"/claims/{claim_id}")
        return resp.json() if resp.status_code == 200 else {"error": f"claim {claim_id} not found"}

    @tool
    def get_provider_history(provider_npi: str) -> list[dict]:
        """List the provider's claims (id, member, service code, date, status, paid)."""
        resp = unet.get(f"/providers/{provider_npi}/claims")
        if resp.status_code != 200:
            return [{"error": "provider not found"}]
        return [
            {
                "claim_id": c["claim_id"],
                "member_id": c["member_id"],
                "cpt_code": c["cpt_code"],
                "service_date": c["service_date"],
                "status": c["status"],
                "denial_carc": c["denial_carc"],
                "paid_amount": c["paid_amount"],
            }
            for c in resp.json()[:25]
        ]

    @tool
    def fee_schedule_lookup(cpt_code: str) -> dict:
        """Fee-schedule allowed amount and description for a CPT/HCPCS code."""
        resp = unet.get(f"/fee-schedule/{cpt_code}")
        return resp.json() if resp.status_code == 200 else {"error": f"{cpt_code} not on schedule"}

    @tool
    def get_prior_rework(claim_id: str) -> list[dict]:
        """Prior rework tickets that reference this claim."""
        resp = servicenow.get("/tickets")
        if resp.status_code != 200:
            return []
        return [
            {"sys_id": t["sys_id"], "state": t["state"], "summary": t["short_description"]}
            for t in resp.json()
            if t["claim_id"] == claim_id
        ]

    @tool
    def submit_recommendation(
        action: str, rationale: str, confidence: float, adjustment_amount: str | None = None
    ) -> str:
        """Submit your final recommendation. Call exactly once, after investigating.

        action: no_change | adjust_up | adjust_down | uphold_denial | reprocess |
        route_specialist. adjustment_amount: exact decimal string, required for
        adjust_up/adjust_down. confidence: 0-1.
        """
        try:
            Action(action)
        except ValueError:
            return f"invalid action '{action}' — pick one of {[a.value for a in Action]}"
        capture.update(
            action=action,
            rationale=rationale,
            confidence=max(0.0, min(1.0, confidence)),
            adjustment_amount=adjustment_amount,
        )
        return "recommendation recorded"

    return [
        get_claim,
        get_provider_history,
        fee_schedule_lookup,
        get_prior_rework,
        submit_recommendation,
    ]
