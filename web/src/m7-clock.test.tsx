import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';
import type { Entry } from './types';

const start = '2026-10-28T07:59:00+04:00';
const clientStart = new Date('2035-01-01T00:00:00Z').getTime();
const deadline = { status: 'found', normalized: '2026-10-28T08:00:00+04:00' };
const entry = { id: 1, kind: 'call', display_title: 'Lantern Forge', provider_id: 'm7-clock',
    deadline, deadline_group: 'timed', attention_reason: 'Expired', status: 'new' } as Entry;

async function show(frozen = false, mode = 'local') {
    vi.useFakeTimers();
    vi.setSystemTime(clientStart);
    const now = () => frozen ? start : new Date(new Date(start).getTime() + Date.now() - clientStart).toISOString();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        const overdue = new Date(now()) >= new Date(deadline.normalized);
        const current = { ...entry, deadline_group: overdue ? 'overdue' : 'timed' };
        const data: Record<string, unknown> = {
            '/api/settings': { mode, paused: false, clock: now(), frozen_clock: frozen },
            '/api/runs': [],
            '/api/today': { now: now(), snapshot: { stale: false }, attention: overdue ? [current] : [],
                deadlines_48h: overdue ? [] : [current], new_calls: [], admin_tasks: [],
                date_only: [], uncertain_deadlines: [], outside_applications: [] },
            '/api/opportunities': [{ id: 1, status: 'new', display_title: 'Lantern Forge', fields: { deadline } }],
            '/api/messages': [{ id: 1, opportunity_id: 1, provider_id: 'm7-clock', category: 'ps_call', original_category: 'ps_call',
                subject: 'Lantern Forge', fields: {}, classification_history: [], received_at: start,
                sent_at: start, source_quote: '', body_text: '', corrected_category: null }],
        };
        return { ok: true, json: async () => data[url] };
    }));
    render(<MemoryRouter><App /></MemoryRouter>);
    await act(async () => { });
}
function group(title: string) { return within(screen.getByRole('heading', { name: title }).closest('[data-slot="card"]')! as HTMLElement); }
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('regroups Today and due filters from 07:59 to 08:01 using the server anchor', async () => {
    await show();
    expect(group('Deadlines within 48 hours').getByText('Lantern Forge')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Attention:', { exact: true }), { target: { value: 'due' } });
    expect(screen.getByText('Showing 1 of 1 messages')).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
    expect(group('Deadlines within 48 hours').queryByText('Lantern Forge')).toBeNull();
    expect(group('Overdue / blocked').getByText('Lantern Forge')).toBeTruthy();
    expect(screen.getByText('No messages match these filters.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Attention:', { exact: true }), { target: { value: 'overdue' } });
    expect(screen.getByText('Showing 1 of 1 messages')).toBeTruthy();
    expect(screen.getAllByText('Expired · 0 h 1 min overdue').length).toBeGreaterThan(0);
});

it('catches up on tab return using elapsed time without counting timer callbacks', async () => {
    await show();
    vi.setSystemTime(clientStart + 2 * 3600000);
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(group('Overdue / blocked').getByText('Lantern Forge')).toBeTruthy();
    expect(screen.getAllByText('Expired · 1 h 59 min overdue').length).toBeGreaterThan(0);
});

it.each(['local', 'replay'])('preserves the frozen synthetic clock in %s', async mode => {
    await show(true, mode);
    await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
    expect(group('Deadlines within 48 hours').getByText('Lantern Forge')).toBeTruthy();
    expect(group('Overdue / blocked').queryByText('Lantern Forge')).toBeNull();
    expect(screen.getAllByText('0 h 1 min left').length).toBeGreaterThan(0);
});
