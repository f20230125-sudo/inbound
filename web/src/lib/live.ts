import { useEffect, useRef, useState } from 'react';
import { DATA_CHANGED, request } from './api';
import type { AgentStep, Entry, StepsPage, Today } from '../types';

export type LiveState = { status: 'connecting' | 'live' | 'reconnecting'; checkedAt?: Date };
const INTERVAL_MS = 10000;
export const ALERTS_KEY = 'inbound-alerts';
const SEEN_KEY = 'inbound-alerted';

function stored<T>(key: string, fallback: T): T {
    try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) as T : fallback; }
    catch { return fallback; }
}
function store(key: string, value: unknown) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* alerts still work this session */ }
}
export function alertsEnabled() {
    return stored<string>(ALERTS_KEY, 'off') === 'on' && typeof Notification !== 'undefined' && Notification.permission === 'granted';
}
export function setAlertsEnabled(on: boolean) { store(ALERTS_KEY, on ? 'on' : 'off'); }

/** Alerts on this PC only: a new PS call, or a deadline within 12 h not yet acted on. */
export function alertsFor(today: Today, now: Date, seen: string[]): { key: string; title: string; body: string; id: number; task?: boolean }[] {
    const out: { key: string; title: string; body: string; id: number; task?: boolean }[] = [];
    // A call can leave 'new' within seconds (blocked by a missing JD, or given a draft pack),
    // so look for first sightings across every Today list, not only new_calls.
    const lists = [today.new_calls, today.attention, today.deadlines_48h, today.date_only, today.uncertain_deadlines];
    const firstSeen = new Set<number>();
    for (const entry of lists.flat()) {
        if (entry.kind === 'ps_admin' || entry.kind === 'task' || firstSeen.has(entry.id)) continue;
        firstSeen.add(entry.id);
        out.push({ key: `new:${entry.id}`, title: 'New PS call', body: entry.display_title, id: entry.id });
    }
    for (const task of today.college_tasks || []) {
        const value = task.deadline.normalized;
        if (!task.actionable || !['found', 'inferred'].includes(task.deadline.status) || typeof value !== 'string' || value.length <= 10) continue;
        const hours = (new Date(value).getTime() - now.getTime()) / 3600000;
        if (hours > 0 && hours <= 12) out.push({ key: `task12:${task.id}:${value}`, title: 'College task within 12 hours', body: `${task.course || 'Course unknown'} · ${task.title}`, id: task.id, task: true });
    }
    const applied = new Set((today.outside_applications || []).map(a => a.id));
    for (const entry of today.deadlines_48h as Entry[]) {
        const value = entry.deadline?.normalized;
        if (typeof value !== 'string' || value.length <= 10 || applied.has(entry.id) || ['skipped', 'submitted_by_me'].includes(entry.status || '')) continue;
        const hours = (new Date(value).getTime() - now.getTime()) / 3600000;
        // The key carries the deadline itself, so an amended deadline alerts again.
        if (hours > 0 && hours <= 12) out.push({ key: `due12:${entry.id}:${value}`, title: 'Deadline within 12 hours', body: `${entry.display_title} · ${entry.deadline_label}`, id: entry.id });
    }
    return out.filter(a => !seen.includes(a.key));
}

async function notify(today: Today, primeOnly: boolean, allowed: () => boolean) {
    const seen = stored<string[]>(SEEN_KEY, []);
    const fresh = alertsFor(today, new Date(), seen);
    if (!fresh.length) return;
    store(SEEN_KEY, [...seen, ...fresh.map(a => a.key)].slice(-500));
    if (primeOnly || !allowed() || !alertsEnabled()) return;
    const settings = await request<import('../types').Settings>('/settings');
    if (!allowed() || settings.mode !== 'local' || settings.paused || !settings.csrf_token) return;
    for (const alert of fresh) {
        if (!allowed()) return;
        const facts = { ...(alert.task ? { task_id: alert.id } : { opportunity_id: alert.id }), alert_type: alert.task ? 'task_deadline' : alert.key.startsWith('due12:') ? 'deadline' : 'new_call' };
        async function record(kind: string, reason: string) {
            try { await request('/agent/alerts', settings.csrf_token, { ...facts, kind, reason }); }
            catch { /* A guard may have changed since this check; never bypass it. */ }
        }
        await record('eligible', 'eligible');
        if (!allowed()) return;
        if (!alertsEnabled()) { await record('suppressed', 'disabled'); continue; }
        try {
            const shown = new Notification(alert.title, { body: alert.body, tag: alert.key });
            shown.onclick = () => { window.focus(); window.location.assign(alert.task ? `/work#task-${alert.id}` : `/opportunity/${alert.id}`); };
            await record('requested', 'requested');
        } catch { await record('suppressed', 'failed'); }
    }
}

/** Watches the server's change token; when it moves, every open view refetches in place. */
export function useLive(refresh: () => Promise<void>, enabled: boolean, streamEnabled = true): LiveState {
    const [state, setState] = useState<LiveState>({ status: 'connecting' });
    const last = useRef<string | undefined>(undefined);
    const primed = useRef(false);
    const alerted = useRef(0);
    useEffect(() => {
        if (!enabled) return;
        let stopped = false;
        let stream: EventSource | undefined;
        let resourceTimer: number | undefined;
        let cursor = 0;
        async function connectStream() {
            if (!streamEnabled || typeof EventSource === 'undefined') return;
            try {
                const history = await request<StepsPage>('/agent/steps');
                if (stopped) return;
                cursor = history.after;
                stream = new EventSource(`/api/agent/stream?after=${cursor}`);
                stream.onmessage = event => {
                    try {
                        const step = JSON.parse(event.data) as AgentStep;
                        if (stopped || step.id <= cursor) return;
                        cursor = step.id;
                        if (resourceTimer === undefined) resourceTimer = window.setTimeout(() => {
                            resourceTimer = undefined;
                            window.dispatchEvent(new Event(DATA_CHANGED));
                            void refresh();
                        }, 250);
                    } catch { /* The version fallback can recover a malformed stream frame. */ }
                };
            } catch { /* Version polling remains available if catch-up or SSE is unavailable. */ }
        }
        void connectStream();
        async function check() {
            if (document.hidden) return;
            try {
                const { version } = await request<{ version: string }>('/version');
                if (stopped) return;
                const changed = last.current !== undefined && last.current !== version;
                last.current = version;
                setState({ status: 'live', checkedAt: new Date() });
                if (changed) { window.dispatchEvent(new Event(DATA_CHANGED)); await refresh(); }
                // Deadlines cross the 12 h line with no data change, so alerts re-check each minute.
                if (changed || !primed.current || Date.now() - alerted.current >= 60000) {
                    // First pass only records what already exists, so opening the desk is quiet.
                    await notify(await request<Today>('/today'), !primed.current, () => !stopped);
                    primed.current = true;
                    alerted.current = Date.now();
                }
            } catch { if (!stopped) setState(s => ({ ...s, status: 'reconnecting' })); }
        }
        void check();
        const timer = window.setInterval(() => void check(), INTERVAL_MS);
        const visible = () => { if (!document.hidden) void check(); };
        document.addEventListener('visibilitychange', visible);
        return () => { stopped = true; stream?.close(); clearTimeout(resourceTimer); clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
    }, [refresh, enabled, streamEnabled]);
    return state;
}
