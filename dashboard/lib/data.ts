import type { Snapshot, Ticket } from "./types";
import snapshotJson from "./demo-snapshot.json";

// Live mode: point NEXT_PUBLIC_GATEWAY_URL at the FastAPI gateway (mocks running).
// Demo mode (default, and the Vercel deployment): the committed snapshot.
export const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "";
export const DEMO_MODE = GATEWAY === "";

const snapshot = snapshotJson as unknown as Snapshot;

export async function getSnapshot(): Promise<Snapshot> {
  if (DEMO_MODE) return snapshot;
  const [queue, metrics] = await Promise.all([
    fetch(`${GATEWAY}/api/queue`, { cache: "no-store" }).then((r) => r.json()),
    fetch(`${GATEWAY}/api/metrics`, { cache: "no-store" }).then((r) => r.json()),
  ]);
  return {
    generated_at: new Date().toISOString(),
    model: "live",
    n: metrics.total,
    metrics: {
      by_source: metrics.by_source,
      by_action: {},
      stp_released: metrics.stp_released,
      jobs_succeeded: metrics.jobs_succeeded,
      pending_approval: metrics.by_state?.pending_approval ?? queue.length,
    },
    tickets: queue,
  };
}

export async function getTicket(sysId: string): Promise<Ticket | null> {
  if (DEMO_MODE) {
    return snapshot.tickets.find((t) => t.sys_id === sysId) ?? null;
  }
  const resp = await fetch(`${GATEWAY}/api/tickets/${sysId}`, { cache: "no-store" });
  return resp.ok ? resp.json() : null;
}
