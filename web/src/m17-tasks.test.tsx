import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { CollegeTasks } from './components/college-tasks';
import { DailyBriefing } from './components/daily-briefing';
import { ScoutCommand } from './components/scout-command';
import { alertsFor } from './lib/live';
import type { Today } from './types';

vi.mock('./App', () => ({ useDesk: () => ({ settings: { mode: 'local', csrf_token: 'test', paused: false, clock: '2026-10-28T10:00:00+04:00' }, recordedReplay: false, refresh: vi.fn() }) }));
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });
const task = { id: 1, course: 'CS F211', title: 'Quiz 1', version: 2, state: 'open', actionable: true, deadline: { status: 'found', normalized: '2026-10-28T18:00:00+04:00' }, source_quote: 'Quiz on 28 October 2026 at 6 PM.', history: [{ id: 1, message_id: 1, deadline_json: '{}', source_quote: 'Original quiz date.' }] };

it('shows task evidence and sends a version-bound manual action followed by Undo', async () => {
    const writes: unknown[] = [];
    let current = task;
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => {
        if (options?.body) { const body = JSON.parse(options.body as string); writes.push(body); current = { ...current, state: body.action === 'done' ? 'done' : 'open', version: current.version + 1 }; }
        return { ok: true, json: async () => options?.body ? current : { items: [current] } };
    }));
    render(<MemoryRouter><CollegeTasks /></MemoryRouter>);
    await act(async () => {});
    expect(screen.getByText('CS F211 · Quiz 1')).toBeTruthy();
    expect(screen.getByText(task.source_quote)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Done' })));
    expect(writes).toEqual([{ action: 'done', expected_version: 2 }]);
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Undo task action' })));
    expect(writes[1]).toEqual({ action: 'undo', expected_version: 3 });
});

it('shows an immutable recorded briefing without requesting generation', async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ id: 9, day: '2026-10-27', greeting: 'Good morning.', freshness: 'Stored work.', created_at: '2026-10-27T08:00:00+04:00', items: [{ kind: 'task', text: 'I found Quiz 1 due tomorrow.', href: '/work#task-1', source_refs: [{ entity_type: 'task', entity_id: 1 }] }] }) }));
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter initialEntries={['/?briefing=9']}><DailyBriefing /></MemoryRouter>);
    await act(async () => {});
    expect(screen.getByText(/Recorded briefing/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'I found Quiz 1 due tomorrow.' })).toBeTruthy();
    expect(fetcher.mock.calls.every(args => !(args as unknown as [string, RequestInit])[1]?.method)).toBe(true);
});

it('alerts only actionable supported timed college tasks within 12 hours, with separate identity', () => {
    const today = { new_calls: [], attention: [], deadlines_48h: [], date_only: [], uncertain_deadlines: [], college_tasks: [task, { ...task, id: 2, actionable: false }, { ...task, id: 3, deadline: { status: 'found', normalized: '2026-10-28' } }, { ...task, id: 4, deadline: { status: 'conflicting' } }] } as unknown as Today;
    const alerts = alertsFor(today, new Date('2026-10-28T10:00:00+04:00'), []);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].key).toBe('task12:1:2026-10-28T18:00:00+04:00');
    expect(alerts[0].title).toBe('College task within 12 hours');
    expect(alertsFor(today, new Date('2026-10-28T10:00:00+04:00'), [alerts[0].key])).toEqual([]);
});

it('keeps task citations in conversation and opens their source evidence', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes('/citation?') ? { entity_type: 'task', label: 'College task', version: 2, href: '/work#task-1', content: { course: task.course, title: task.title, deadline: task.deadline, source_quote: task.source_quote } } : { text: 'I found one college task.', items: [{ text: 'Quiz 1', citations: [{ entity_type: 'task', entity_id: 1, version: 2, label: 'College task', url: '/api/scout/citation?ticket=task' }] }], choices: [], suggestions: [] } })));
    render(<MemoryRouter><ScoutCommand returnToWork={() => {}} /></MemoryRouter>);
    const input = screen.getByRole('textbox', { name: 'Ask Scout or give a command' });
    fireEvent.change(input, { target: { value: 'what assignments are due' } });
    await act(async () => fireEvent.submit(input.closest('form')!));
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'College task · version 2' })));
    expect(screen.getByText(task.source_quote)).toBeTruthy();
    expect(sessionStorage.getItem('inbound-scout-history-v1')).toContain('Quiz 1');
});
