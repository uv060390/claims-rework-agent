import Link from "next/link";
import { getSnapshot } from "@/lib/data";
import type { Ticket } from "@/lib/types";

const SOURCE_COLORS: Record<string, string> = {
  classifier: "#6d28d9",
  rule: "#0e7490",
  agent: "#c2410c",
};

function favClass(t: Ticket): string {
  const rec = t.recommendation;
  if (!rec) return "neutral";
  if (rec.action === "adjust_up" || rec.action === "reprocess") return "favorable";
  if (rec.action === "adjust_down" || rec.action === "uphold_denial") return "unfavorable";
  return "neutral";
}

export default async function Home() {
  const snap = await getSnapshot();
  const total = snap.n;
  const bySource = snap.metrics.by_source;
  const pending = snap.tickets
    .filter((t) => t.state === "pending_approval")
    .sort((a, b) => (a.sys_id < b.sys_id ? -1 : 1));
  const resolved = snap.tickets.filter((t) => t.state !== "pending_approval");
  const autoClosed = snap.tickets.filter(
    (t) => t.state === "closed" && t.recommendation?.source === "classifier"
  ).length;

  return (
    <main>
      <div className="tiles">
        <div className="tile">
          <div className="label">Requests processed</div>
          <div className="value">{total}</div>
          <div className="hint">batch of {snap.n} · {snap.model}</div>
        </div>
        <div className="tile">
          <div className="label">Auto-closed (classifier)</div>
          <div className="value">{autoClosed}</div>
          <div className="hint">{((autoClosed / total) * 100).toFixed(0)}% of volume</div>
        </div>
        <div className="tile">
          <div className="label">STP released</div>
          <div className="value">{snap.metrics.stp_released}</div>
          <div className="hint">favorable-only, no human needed</div>
        </div>
        <div className="tile">
          <div className="label">Pending approval</div>
          <div className="value">{pending.length}</div>
          <div className="hint">awaiting analyst decision</div>
        </div>
        <div className="tile">
          <div className="label">Executed on platform</div>
          <div className="value">{snap.metrics.jobs_succeeded}</div>
          <div className="hint">via RPA queue</div>
        </div>
      </div>

      <div className="card">
        <h2>Resolution funnel</h2>
        <div className="funnel">
          {(["classifier", "rule", "agent"] as const).map((s) => (
            <div
              key={s}
              style={{
                width: `${((bySource[s] ?? 0) / total) * 100}%`,
                background: SOURCE_COLORS[s],
              }}
            />
          ))}
        </div>
        <div className="legend">
          {(["classifier", "rule", "agent"] as const).map((s) => (
            <span key={s}>
              <span className="dot" style={{ background: SOURCE_COLORS[s] }} />
              {s} · {bySource[s] ?? 0} ({(((bySource[s] ?? 0) / total) * 100).toFixed(1)}%)
            </span>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>Work queue — pending approval ({pending.length})</h2>
        <table>
          <thead>
            <tr>
              <th>Ticket</th>
              <th>Claim</th>
              <th>Recommendation</th>
              <th>Amount</th>
              <th>Source</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {pending.map((t) => (
              <tr key={t.sys_id} className="rowlink">
                <td>
                  <Link href={`/ticket/${t.sys_id}`} className="mono" style={{ color: "#2563eb" }}>
                    {t.sys_id}
                  </Link>
                </td>
                <td>
                  <span className="mono">{t.claim?.cpt_code}</span>{" "}
                  <span className="muted">{t.claim?.service_date}</span>
                  {t.claim?.denial_carc ? (
                    <span className="muted"> · CARC {t.claim.denial_carc}</span>
                  ) : null}
                </td>
                <td>
                  <span className={`badge ${favClass(t)}`}>{t.recommendation?.action}</span>
                </td>
                <td className="mono">
                  {t.recommendation?.adjustment_amount
                    ? `$${t.recommendation.adjustment_amount}`
                    : "—"}
                </td>
                <td>
                  <span className={`badge ${t.recommendation?.source}`}>
                    {t.recommendation?.source}
                  </span>
                </td>
                <td className="mono">
                  {t.recommendation ? `${(t.recommendation.confidence * 100).toFixed(0)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Recently resolved ({resolved.length})</h2>
        <table>
          <thead>
            <tr>
              <th>Ticket</th>
              <th>Action</th>
              <th>Source</th>
              <th>State</th>
              <th>Execution</th>
            </tr>
          </thead>
          <tbody>
            {resolved.slice(0, 25).map((t) => (
              <tr key={t.sys_id} className="rowlink">
                <td>
                  <Link href={`/ticket/${t.sys_id}`} className="mono" style={{ color: "#2563eb" }}>
                    {t.sys_id}
                  </Link>
                </td>
                <td>
                  <span className={`badge ${favClass(t)}`}>{t.recommendation?.action}</span>
                </td>
                <td>
                  <span className={`badge ${t.recommendation?.source}`}>
                    {t.recommendation?.source}
                  </span>
                </td>
                <td>
                  <span className={`badge state ${t.state}`}>{t.state}</span>
                </td>
                <td className="muted">
                  {t.job ? `${t.job.job_id} · ${t.job.status}` : "no execution needed"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {resolved.length > 25 && (
          <p className="muted" style={{ marginBottom: 0 }}>
            …and {resolved.length - 25} more in the snapshot.
          </p>
        )}
      </div>
    </main>
  );
}
