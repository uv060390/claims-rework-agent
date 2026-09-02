"""Recommend-then-Release orchestrator — binds classifier, rules, agent, and gate.

The straight-through-processing gate lives HERE, in plain code, deliberately
outside the agent: favorability is recomputed from the recommended ACTION itself,
so no layer (least of all the LLM) can label its own output safe for auto-release.
Denials and recoupments always wait for a human Approve.
"""

import json

from pipeline.agent.graph import run_triage
from pipeline.classifier.infer import NANClassifier
from pipeline.ledger import Ledger, hash_payload
from pipeline.rules.engine import RulesEngine
from pipeline.schemas import Action, LedgerEvent, Recommendation, Source

STP_ACTIONS = frozenset({Action.ADJUST_UP, Action.REPROCESS})
EXECUTABLE_ACTIONS = frozenset({Action.ADJUST_UP, Action.ADJUST_DOWN, Action.REPROCESS})


def stp_eligible(rec: Recommendation) -> bool:
    """Favorable-only STP, derived from the action — the rec's own flag is ignored."""
    return rec.action in STP_ACTIONS


class Orchestrator:
    def __init__(
        self,
        *,
        unet,
        servicenow,
        uipath,
        ledger: Ledger,
        classifier: NANClassifier | None = None,
        rules: RulesEngine | None = None,
        llm=None,
    ):
        self.unet = unet
        self.servicenow = servicenow
        self.uipath = uipath
        self.ledger = ledger
        self.classifier = classifier if classifier is not None else NANClassifier()
        self.rules = rules if rules is not None else RulesEngine()
        self.llm = llm
        self._recommendations: dict[str, Recommendation] = {}

    def _log(self, request_id: str, layer: str, decision: str, payload: dict) -> None:
        self.ledger.append(
            LedgerEvent(
                request_id=request_id,
                layer=layer,
                decision=decision,
                payload_hash=hash_payload(payload),
            )
        )

    def _note(self, sys_id: str, rec: Recommendation) -> None:
        body = rec.model_dump(mode="json")
        self.servicenow.post(
            f"/tickets/{sys_id}/work_notes",
            json={"note": json.dumps(body), "author": rec.source.value},
        )

    def process(self, request: dict) -> dict:
        """Run one rework request through the full pipeline. Returns an outcome summary."""
        request_id = request["request_id"]
        claim = self.unet.get(f"/claims/{request['claim_id']}").json()
        original = None
        if claim.get("original_claim_id"):
            resp = self.unet.get(f"/claims/{claim['original_claim_id']}")
            original = resp.json() if resp.status_code == 200 else None

        ticket = self.servicenow.post(
            "/tickets",
            json={
                "request_id": request_id,
                "claim_id": claim["claim_id"],
                "short_description": f"rework: {claim['cpt_code']} {claim['service_date']}",
            },
        ).json()
        sys_id = ticket["sys_id"]
        self._log(request_id, "intake", "ticket_created", ticket)

        # layer 1 — NAN classifier
        prob, auto_close = self.classifier.predict(request, claim, original)
        self._log(request_id, "classifier", f"p_nan={prob:.4f}", {"prob": prob, "auto": auto_close})
        if auto_close:
            rec = Recommendation(
                action=Action.NO_CHANGE,
                adjustment_amount=None,
                rationale=f"NAN classifier auto-close at p={prob:.3f} "
                f"(threshold {self.classifier.threshold:.3f}).",
                confidence=prob,
                favorable_to_provider=False,
                source=Source.CLASSIFIER,
            )
            self._note(sys_id, rec)
            self.servicenow.post(f"/tickets/{sys_id}/transition", json={"state": "closed"})
            self._log(request_id, "gate", "auto_closed", rec.model_dump(mode="json"))
            return self._outcome(request_id, sys_id, rec, released=False, job=None)

        # layer 2 — rules engine
        rec = self.rules.evaluate(request, claim, original)
        if rec is not None:
            self._log(request_id, "rules", rec.rule_id or "rule", rec.model_dump(mode="json"))
        else:
            # layer 3 — triage agent
            rec, _trace = run_triage(
                request, claim, unet=self.unet, servicenow=self.servicenow, llm=self.llm
            )
            self._log(request_id, "agent", rec.action.value, rec.model_dump(mode="json"))

        self._note(sys_id, rec)
        self._recommendations[sys_id] = rec

        # layer 4 — the gate
        if rec.action == Action.ROUTE_SPECIALIST:
            self.servicenow.post(f"/tickets/{sys_id}/transition", json={"state": "in_review"})
            self._log(request_id, "gate", "routed_to_specialist", rec.model_dump(mode="json"))
            return self._outcome(request_id, sys_id, rec, released=False, job=None)

        self.servicenow.post(f"/tickets/{sys_id}/transition", json={"state": "pending_approval"})
        if stp_eligible(rec):
            self.servicenow.post(
                f"/tickets/{sys_id}/transition", json={"state": "approved", "actor": "stp-gate"}
            )
            self._log(request_id, "gate", "stp_released", rec.model_dump(mode="json"))
            job = self.release(sys_id)
            return self._outcome(request_id, sys_id, rec, released=True, job=job)

        self._log(request_id, "gate", "pending_human_approval", rec.model_dump(mode="json"))
        return self._outcome(request_id, sys_id, rec, released=False, job=None)

    def release(self, sys_id: str) -> dict | None:
        """Execute an approved recommendation: queue executable actions, close the rest.

        Called by the STP path and, on analyst approval, by the gateway/webhook.
        """
        rec = self._recommendations[sys_id]
        ticket = self.servicenow.get(f"/tickets/{sys_id}").json()
        request_id = ticket["request_id"]
        if rec.action not in EXECUTABLE_ACTIONS:
            self.servicenow.post(f"/tickets/{sys_id}/transition", json={"state": "closed"})
            self._log(request_id, "execute", "closed_no_execution", {"action": rec.action.value})
            return None
        job = self.uipath.post(
            "/queues/claims-rework/jobs",
            json={
                "ticket_id": sys_id,
                "claim_id": ticket["claim_id"],
                "action": rec.action.value,
                "amount": str(rec.adjustment_amount) if rec.adjustment_amount else None,
            },
        ).json()
        final = self.uipath.get(f"/jobs/{job['job_id']}").json()
        self._log(request_id, "execute", f"job_{final['status']}", final)
        return final

    @staticmethod
    def _outcome(request_id, sys_id, rec: Recommendation, *, released: bool, job) -> dict:
        return {
            "request_id": request_id,
            "ticket_id": sys_id,
            "resolved_by": rec.source.value,
            "action": rec.action.value,
            "confidence": rec.confidence,
            "stp_released": released,
            "job_status": job["status"] if job else None,
        }
