import { useEffect, useRef, useState } from 'react';
import { DATA_CHANGED, request } from './api';
import type { Entry, Today } from '../types';

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
export function alertsFor(today: Today, now: Date, seen: string[]): { key: string; title: string; body: string; id: number }[] {
    const out: { key: string; title: string; body: string; id: number }[] = [];
    for (const entry of today.new_calls) {
        if (entry.kind !== 'ps_admin') out.push({ key: `new:${entry.id}`, title: 'New PS call', body: entry.display_title, id: entry.id });
    }
    const applied = new Set((today.outside_applications || []).map(a => a.id));
    for (const entry of today.deadlines_48h as Entry[]) {
        const value = entry.deadline?.normalized;
        if (typeof value !== 'string' || value.length <= 10 || applied.has(entry.id) || ['skipped', 'submitted_by_me'].includes(entry.status || '')) continue;
        const hours = (new Date(value).getTime() - now.getTime()) / 3600000;
        if (hours > 0 && hours <= 12) out.push({ key: `due12:${entry.id}`, title: 'Deadline within 12 hours', body: `${entry.display_title} · ${entry.deadline_label}`, id: entry.id });
    }
    return out.filter(a => !seen.includes(a.key));
}

async function notify(today: Today, primeOnly: boolean) {
    const seen = stored<string[]>(SEEN_KEY, []);
    const fresh = alertsFor(today, new Date(), seen);
    if (!fresh.length) return;
    store(SEEN_KEY, [...seen, ...fresh.map(a => a.key)].slice(-500));
    if (primeOnly || !alertsEnabled()) return;
    for (const alert of fresh) {
        const shown = new Notification(alert.title, { body: alert.body, tag: alert.key });
        shown.onclick = () => { window.focus(); window.location.assign(`/opportunity/${alert.id}`); };
    }
}

/** Watches the server's change token; when it moves, every open view refetches in place. */
export function useLive(refresh: () => Promise<void>, enabled: boolean): LiveState {
    const [state, setState] = useState<LiveState>({ status: 'connecting' });
    const last = useRef<string | undefined>(undefined);
    const primed = useRef(false);
    const alerted = useRef(0);
    useEffect(() => {
        if (!enabled) return;
        let stopped = false;
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
                    await notify(await request<Today>('/today'), !primed.current);
                    primed.current = true;
                    alerted.current = Date.now();
                }
            } catch { if (!stopped) setState(s => ({ ...s, status: 'reconnecting' })); }
        }
        void check();
        const timer = window.setInterval(() => void check(), INTERVAL_MS);
        const visible = () => { if (!document.hidden) void check(); };
        document.addEventListener('visibilitychange', visible);
        return () => { stopped = true; clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
    }, [refresh, enabled]);
    return state;
}
