import type { Field, Opportunity } from '../types';
export const categories: Record<string, string> = { ps_call: 'PS call', ps_admin: 'PS administration', application_update: 'Application update', job_alert: 'Job alert', academic: 'Academic', campus_notice: 'Campus notice', research: 'Research', dev_ops: 'Development / operations', account_billing: 'Account / billing', personal: 'Personal', newsletter_promo: 'Newsletter / promotion', needs_review: 'Needs review' };
export const statuses: Record<string, string> = { new: 'New', preparing: 'Preparing', needs_review: 'Needs review', reviewed: 'Reviewed', submitted_by_me: 'Submitted by me', blocked: 'Blocked', skipped: 'Skipped' };
export function label(value: string) { return categories[value] || statuses[value] || value.charAt(0).toUpperCase() + value.slice(1).replaceAll('_', ' '); }
export function badgeVariant(value: string): 'outline' | 'review' | 'destructive' | 'success' {
    if (value === 'Passed')
        return 'success';
    if (['Expired', 'Failed'].includes(value))
        return 'destructive';
    if (['Needs review', 'Conflicting', 'Inferred', 'Blocked'].includes(value))
        return 'review';
    return 'outline';
}
export function normalizeSubject(value: string) { return value.replace(/[\u200B-\u200D\uFEFF]/g, '').replace(/[–—−]/g, '-').replace(/\s+/g, ' ').trim().replace(/^(?:(?:re|fwd):\s*)+/i, ''); }
export function fallbackTitle(value: string) { return normalizeSubject(value).replace(/^Call for CV\s*-\s*(?:PS II\s*-\s*Second Semester\s+\d{4}\s*-\s*\d{4}\s*-\s*)?/i, ''); }
export function cityText(value: unknown) {
    const values = [...new Set((Array.isArray(value) ? value : [value]).filter(Boolean).map(v => String(v).replace(/[\u200B-\u200D\uFEFF]/g, '').trim()))];
    return values.length ? values[0] + (values.length > 1 ? ` (${values.slice(1).join('; ')})` : '') : 'City unknown';
}
export function callTitle(value: {
    company?: unknown;
    city?: unknown;
    roles?: {
        title: string;
    }[] | null;
    subject?: string;
}) {
    const roles = value.roles || [];
    const role = roles.length > 1 ? `${roles.length} roles` : roles[0]?.title || 'Role unknown';
    return value.company ? [value.company, role, cityText(value.city)].map(v => String(v).replace(/[\u200B-\u200D\uFEFF]/g, '')).join(' · ') : fallbackTitle(value.subject || '');
}
export function opportunityTitle(op: Opportunity) { return op.display_title || callTitle({ company: op.fields.company?.normalized, city: op.fields.city?.normalized, roles: op.fields.roles?.normalized as {
        title: string;
    }[] | null, subject: op.normalized_subject }); }
export function date(value?: string | null, dateOnly = false) {
    if (!value)
        return 'Not recorded';
    const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Dubai', day: '2-digit', month: 'short', year: 'numeric', ...(!dateOnly && value.length > 10 ? { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' as const } : {}) }).format(new Date(value.length === 10 ? `${value}T12:00:00+04:00` : value));
    return parts;
}
export function fieldValue(value: unknown): string {
    if (value == null || value === '')
        return 'Unknown';
    if (typeof value === 'string' || typeof value === 'number')
        return String(value);
    if (Array.isArray(value))
        return value.map(v => v?.title || fieldValue(v)).join(' · ');
    const v = value as Record<string, unknown>;
    if ('currency' in v)
        return `${v.currency} ${Number(v.min).toLocaleString('en-US')}${v.max !== v.min ? `–${Number(v.max).toLocaleString('en-US')}` : ''}/${v.period}`;
    return Object.entries(v).map(([k, x]) => `${label(k)}: ${fieldValue(x)}`).join(' · ');
}
export function deadlineText(record: Field | null | undefined, now: string) {
    if (record?.status === 'conflicting')
        return { label: 'Deadline conflicting · No countdown', absolute: '', tone: 'review' };
    if (!record || !['found', 'inferred'].includes(record.status) || typeof record.normalized !== 'string')
        return { label: 'Deadline unknown · Expiry unknown', absolute: '', tone: 'review' };
    const value = record.normalized;
    if (value.length === 10)
        return { label: `Due ${date(value, true)} · Time not stated`, absolute: '', tone: value < new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Dubai' }).format(new Date(now)) ? 'past' : 'neutral' };
    const delta = new Date(value).getTime() - new Date(now).getTime();
    const mins = Math.floor(Math.abs(delta) / 60000);
    const duration = `${Math.floor(mins / 60)} h ${mins % 60} min`;
    return { label: `${delta <= 0 ? `Expired · ${duration} overdue` : `${duration} left`}${record.past_at_receipt ? ' · Deadline passed before receipt' : ''}`, absolute: `${date(value)} · Dubai`, tone: delta <= 0 ? 'past' : delta <= 48 * 3600000 ? 'review' : 'neutral' };
}
export function deadlineGroup(record: Field | null | undefined, now: string) {
    if (!record || !['found', 'inferred'].includes(record.status) || typeof record.normalized !== 'string')
        return 3;
    if (record.normalized.length === 10)
        return record.normalized < now.slice(0, 10) ? 2 : 1;
    return new Date(record.normalized) > new Date(now) ? 0 : 2;
}
