export interface Recommendation {
  action: string;
  adjustment_amount: string | null;
  rationale: string;
  confidence: number;
  favorable_to_provider: boolean;
  source: string;
  rule_id?: string | null;
}

export interface Claim {
  claim_id: string;
  member_id: string;
  provider_npi: string;
  provider_name: string;
  service_date: string;
  submitted_date: string;
  cpt_code: string;
  modifiers: string;
  icd10_code: string;
  pos_code: string;
  units: string;
  billed_amount: string;
  allowed_amount: string;
  paid_amount: string;
  status: string;
  denial_carc: string;
  original_claim_id: string;
}

export interface LedgerEntry {
  layer: string;
  decision: string;
  at: string;
}

export interface Job {
  job_id: string;
  status: string;
  attempts: number;
  result?: { resulting_status: string; resulting_paid_amount: string } | null;
}

export interface Ticket {
  sys_id: string;
  request_id: string;
  claim_id: string;
  short_description: string;
  state: string;
  created_at: string;
  claim: Claim | null;
  recommendation: Recommendation | null;
  ledger: LedgerEntry[];
  job: Job | null;
  request_note?: string;
  requester_type?: string;
  has_attachment?: string;
}

export interface Snapshot {
  generated_at: string;
  model: string;
  n: number;
  metrics: {
    by_source: Record<string, number>;
    by_action: Record<string, number>;
    stp_released: number;
    jobs_succeeded: number;
    pending_approval: number;
  };
  tickets: Ticket[];
}
