"use client";

import { useState } from "react";
import { DEMO_MODE, GATEWAY } from "@/lib/data";

export default function DecisionPanel({
  sysId,
  action,
}: {
  sysId: string;
  action: string;
}) {
  const [status, setStatus] = useState<"idle" | "busy" | "approved" | "rejected" | "error">("idle");
  const [detail, setDetail] = useState("");

  const executable = ["adjust_up", "adjust_down", "reprocess"].includes(action);

  async function decide(kind: "approve" | "reject") {
    setStatus("busy");
    if (DEMO_MODE) {
      await new Promise((r) => setTimeout(r, 500));
      if (kind === "approve") {
        setDetail(
          executable
            ? "Simulated: released to the RPA queue — job executed against the claims platform."
            : "Simulated: ticket closed, no platform execution needed for this action."
        );
        setStatus("approved");
      } else {
        setDetail("Simulated: ticket rejected and returned for review.");
        setStatus("rejected");
      }
      return;
    }
    try {
      const resp = await fetch(`${GATEWAY}/api/tickets/${sysId}/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "analyst" }),
      });
      if (!resp.ok) throw new Error(`gateway returned ${resp.status}`);
      const body = await resp.json();
      setDetail(
        kind === "approve"
          ? body.job
            ? `Released — ${body.job.job_id} ${body.job.status}.`
            : "Approved — ticket closed, no execution needed."
          : "Rejected."
      );
      setStatus(kind === "approve" ? "approved" : "rejected");
    } catch (e) {
      setDetail(String(e));
      setStatus("error");
    }
  }

  const done = status === "approved" || status === "rejected";

  return (
    <div>
      <div className="actions">
        <button className="approve" disabled={status === "busy" || done} onClick={() => decide("approve")}>
          {status === "busy" ? "Working…" : "Approve & release"}
        </button>
        <button className="reject" disabled={status === "busy" || done} onClick={() => decide("reject")}>
          Reject
        </button>
      </div>
      {done && <div className={`result-note ${status === "approved" ? "ok" : "bad"}`}>{detail}</div>}
      {status === "error" && <div className="result-note bad">{detail}</div>}
    </div>
  );
}
