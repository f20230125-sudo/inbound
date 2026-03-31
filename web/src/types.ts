export interface Provenance {
    message_id?: string;
    sent_at?: string;
    revision_id?: number;
    location?: string;
    source?: string;
    name?: string;
    locations?: Record<string, unknown>[];
}
export interface Field {
    name?: string;
    status: string;
    normalized?: unknown;
    raw?: string;
    source_text?: string;
    missing_reason?: string;
    candidates?: Field[];
    observations?: {
        value: unknown;
        source_text: string;
        provenance?: Provenance;
    }[];
    provenance?: Provenance;
    inherited?: boolean;
    anchor?: string;
    past_at_receipt?: boolean;
}
export interface Requirement {
    id: string;
    text: string;
    source_text?: string;
    provenance?: Provenance;
}
export interface Selection {
    projects: {
        id: string;
        bullets: string[];
        why: string[];
    }[];
    requirements: Requirement[];
    gaps: Requirement[];
    skills: string[];
    coverage: {
        supported: number;
        total: number;
        ratio: number | null;
    };
    fit: string;
    fit_reason: string;
}
export interface Bullet {
    id: string;
    text_plain: string;
    source_file: string;
    source_line?: number;
    source_hash: string;
}
export interface Project {
    id: string;
    title: string;
    source_file: string;
    source_hash: string;
    bullets: Bullet[];
}
export interface Evidence {
    projects: Project[];
    applicant: Record<string, unknown>;
}
export interface Role {
    id: number;
    title: string;
    requirements: Requirement[] | null;
    coverage: Selection | null;
}
export interface Revision {
    id: number;
    provider_id: string;
    sent_at: string;
    received_at: string;
    subject: string;
    body_text: string;
    fields: Record<string, Field>;
}
export interface Event {
    id: number;
    action: string;
    created_at: string;
    revision_id: number;
    pack_id?: string;
    details: Record<string, unknown>;
}
export interface PackRef {
    content_version?: number;
    id: string;
    revision_id: number;
    status: string;
    created_at: string;
    provisional: number;
}
export interface Opportunity {
    content_version?: number;
    attachment_recoveries?: { id: number; attachment_id: number; original_filename: string; sha256: string; supplier: string; recorded_at: string; parse_status: string; reason: string }[];
    outside_application?: ApplicationActivity | null;
    display_title?: string;
    city_display?: string;
    role_label?: string;
    id: number;
    revision_id: number;
    company: string | null;
    city: string | null;
    status: string;
    kind: string;
    blocked_reason: string | null;
    normalized_subject: string;
    fields: Record<string, Field>;
    roles?: Role[];
    recommended_role_id?: number | null;
    revisions?: Revision[];
    packs?: PackRef[];
    evidence?: Evidence;
    attachments?: {
        id: number;
        filename: string;
        parse_status: string;
        purpose: string;
        provider_id: string;
        revision_id: number;
        locations: Record<string, unknown>[];
        text: string;
    }[];
    merge_suggestions?: {
        candidate_id?: number;
        candidate_opportunity_id?: number;
        other_opportunity_id?: number;
        reason: string;
    }[];
    review_history?: Event[];
}
export interface Message {
    id: number;
    provider_id: string;
    subject: string;
    sender: string;
    received_at: string;
    sent_at: string;
    category: string;
    original_category: string;
    corrected_category: string | null;
    corrected_at: string | null;
    rule_id: string;
    reason: string;
    source_quote: string;
    body_text: string;
    attachment_count: number;
    opportunity_id: number | null;
    fields: Record<string, Field>;
    classification_history: {
        id: number;
        category: string;
        created_at: string;
    }[];
}
export interface Entry {
    id: number;
    kind: string;
    display_title: string;
    subject: string;
    provider_id: string;
    deadline: Field | null;
    deadline_group: string;
    deadline_label: string;
    attention_reason: string;
    mode?: string;
    stipend?: unknown;
    status?: string;
}
export interface Snapshot {
    imported_at: string | null;
    latest_message_at: string | null;
    stale: boolean;
    version: number;
    latest_import_failure: {
        id: number;
    } | null;
}
export interface Today {
    outside_applications?: { id: number; display_title: string; outside_application: ApplicationActivity }[];
    now: string;
    snapshot: Snapshot;
    attention: Entry[];
    deadlines_48h: Entry[];
    date_only: Entry[];
    uncertain_deadlines: Entry[];
    new_calls: Entry[];
    admin_tasks: Entry[];
}
export interface ApplicationActivity {
    id: number;
    recorded_at: string;
    applied_at: string;
    note: string;
    follow_up: string | null;
    previous_activity_id: number | null;
}
export interface Settings {
    mode: 'local' | 'replay';
    source_format: string;
    paused: boolean;
    csrf_token?: string;
    clock: string;
    frozen_clock: boolean;
    execution: string;
    budgets: {
        daily_call_limit: number;
        daily_spend_limit: number;
        currency: string;
        calls_used_today: number;
        spend_used_today: number | null;
        resets_at: string | null;
    };
    payload_policy: {
        private_payloads: string;
        allowlist: string[];
    };
    paths: Record<string, string>;
}
export interface Run {
    id: number;
    operation_key: string | null;
    kind: string;
    status: string;
    started_at: string;
    finished_at: string | null;
    duration_seconds: number | null;
    counts: Record<string, number>;
    stage: string | null;
    error: string | null;
    execution: string;
    mode: string;
    model_calls: number;
    cache_hits: number;
    source_type: string | null;
    opportunity_id: number | null;
    revision_id: number | null;
    pack_id: string | null;
    retry_history: unknown[];
}
export interface Pack extends PackRef {
    blocker_acknowledged: number;
    filename: string;
    pdf_url: string;
    role_id: number;
    selection: Selection;
    checks: Record<string, unknown>;
    evidence: Evidence;
    answers: {
        id: string;
        purpose: string;
        technologies: string;
        challenge_fix: string;
        answer_needed: string[];
        provenance: {
            id: string;
            source_file: string;
            source_hash: string;
        };
    }[];
}
