import Link from "next/link";
import { notFound } from "next/navigation";
import DecisionPanel from "@/components/DecisionPanel";
import { getTicket } from "@/lib/data";

function favClass(action?: string): string {
  if (action === "adjust_up" || action === "reprocess") return "favorable";
  if (action === "adjust_down" || action === "uphold_denial") return "unfavorable";
  return "neutral";
}

export default async function TicketPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const ticket = await getTicket(id);
  if (!ticket) notFound();
  const rec = ticket.recommendation;
  const claim = ticket.claim;

  return (
    <main>
      <p>
        <Link href="/" className="backlink">
          ← back to queue
        </Link>
      </p>
      <div className="topbar">
        <h1 style={{ fontSize: 18 }}>
          <span className="mono">{ticket.sys_id}</span>{" "}
          <span className="muted" style={{ fontWeight: 400 }}>
            · {ticket.short_description}
          </span>
        </h1>
        <span className={`badge state ${ticket.state}`}>{ticket.state}</span>
      </div>

      <div className="card">
        <h2>
          Recommendation{" "}
          <span className={`badge ${rec?.source}`} style={{ marginLeft: 6 }}>
            {rec?.source}
            {rec?.rule_id ? ` · ${rec.rule_id}` : ""}
          </span>
        </h2>
        <div className="facts" style={{ marginBottom: 12 }}>
          <div>
            <div className="label">Action</div>
            <div className="value">
              <span className={`badge ${favClass(rec?.action)}`}>{rec?.action}</span>
            </div>
          </div>
          <div>
            <div className="label">Adjustment</div>
            <div className="value mono">
              {rec?.adjustment_amount ? `$${rec.adjustment_amount}` : "—"}
            </div>
          </div>
          <div>
            <div className="label">Favorable to provider</div>
            <div className="value">{rec?.favorable_to_provider ? "yes" : "no"}</div>
          </div>
          <div>
            <div className="label">Confidence</div>
            <div className="value mono">{rec ? `${(rec.confidence * 100).toFixed(0)}%` : "—"}</div>
            {rec && (
              <div className="conf-track">
                <div className="conf-fill" style={{ width: `${rec.confidence * 100}%` }} />
              </div>
            )}
          </div>
        </div>
        {rec?.rationale && <div className="rationale">{rec.rationale}</div>}
        {ticket.state === "pending_approval" && (
          <DecisionPanel sysId={ticket.sys_id} action={rec?.action ?? ""} />
        )}
      </div>

      <div className="grid2">
        <div className="card" style={{ margin: 0 }}>
          <h2>Claim record</h2>
          {claim ? (
            <div className="facts">
              <div>
                <div className="label">Claim</div>
                <div className="value mono">{claim.claim_id}</div>
              </div>
              <div>
                <div className="label">Service</div>
                <div className="value">
                  <span className="mono">{claim.cpt_code}</span>
                  {claim.modifiers ? <span className="mono"> {claim.modifiers}</span> : null} ·{" "}
                  {claim.units}u
                </div>
              </div>
              <div>
                <div className="label">Dates (service / submitted)</div>
                <div className="value mono">
                  {claim.service_date} / {claim.submitted_date}
                </div>
              </div>
              <div>
                <div className="label">Provider</div>
                <div className="value">
                  {claim.provider_name} <span className="muted mono">{claim.provider_npi}</span>
                </div>
              </div>
              <div>
                <div className="label">Diagnosis / POS</div>
                <div className="value mono">
                  {claim.icd10_code} · POS {claim.pos_code}
                </div>
              </div>
              <div>
                <div className="label">Billed / Allowed / Paid</div>
                <div className="value mono">
                  ${claim.billed_amount} / ${claim.allowed_amount} / ${claim.paid_amount}
                </div>
              </div>
              <div>
                <div className="label">Status</div>
                <div className="value">
                  {claim.status}
                  {claim.denial_carc ? ` · CARC ${claim.denial_carc}` : ""}
                </div>
              </div>
              {claim.original_claim_id && (
                <div>
                  <div className="label">Linked original</div>
                  <div className="value mono">{claim.original_claim_id}</div>
                </div>
              )}
            </div>
          ) : (
            <p className="muted">claim unavailable</p>
          )}
          {ticket.request_note && (
            <>
              <h2 style={{ marginTop: 18 }}>
                Request note{" "}
                <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                  {ticket.requester_type}
                  {ticket.has_attachment === "True" ? " · attachment on file" : " · no attachment"}
                </span>
              </h2>
              <div className="rationale" style={{ borderLeftColor: "#9ca3af" }}>
                {ticket.request_note}
              </div>
            </>
          )}
        </div>

        <div className="card" style={{ margin: 0 }}>
          <h2>Audit trail</h2>
          <ul className="timeline">
            {ticket.ledger.map((e, i) => (
              <li key={i}>
                <div className="layer">{e.layer}</div>
                <div className="decision">
                  {e.decision} <span className="mono">· {e.at.slice(0, 19)}</span>
                </div>
              </li>
            ))}
          </ul>
          {ticket.job && (
            <>
              <h2 style={{ marginTop: 18 }}>Execution</h2>
              <div className="facts">
                <div>
                  <div className="label">Job</div>
                  <div className="value mono">{ticket.job.job_id}</div>
                </div>
                <div>
                  <div className="label">Status</div>
                  <div className="value">
                    {ticket.job.status} · {ticket.job.attempts} attempt(s)
                  </div>
                </div>
                {ticket.job.result && (
                  <div>
                    <div className="label">Result</div>
                    <div className="value mono">
                      {ticket.job.result.resulting_status} · paid $
                      {ticket.job.result.resulting_paid_amount}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
