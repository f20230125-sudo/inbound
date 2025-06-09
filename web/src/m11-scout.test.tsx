import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { Briefing, ScoutFace, expressions } from './components/scout';
import App from './App';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it.each(['idle', 'working', 'needs_decision', 'draft_ready', 'failed', 'paused', 'disconnected'] as const)('labels the real %s expression without animation', mood => {
    const { container } = render(<ScoutFace mood={mood} />);
    expect(screen.getByRole('img', { name: `Scout: ${expressions[mood].label}` })).toBeTruthy();
    expect(container.querySelector('svg')?.getAttribute('data-mood')).toBe(mood);
    expect(container.querySelector('animate')).toBeNull();
});

it('renders factual clauses in source order with evidence links and no added numbers', () => {
    const clauses = [{ text: 'New mail may be missing.', href: '/settings#gmail' },
        { text: '2 decisions need your attention.', href: '/work' }];
    render(<MemoryRouter><Briefing clauses={clauses} /></MemoryRouter>);
    expect(screen.getAllByRole('link').map(a => a.textContent)).toEqual(clauses.map(c => c.text));
    expect(screen.getByText('New mail may be missing.').getAttribute('href')).toBe('/settings#gmail');
    expect(screen.queryByText(/draft|handled|applied/i)).toBeNull();
});

it('shows disconnection from a failed state read, keeps the saved decisions, and recovers without commands', async () => {
    vi.useFakeTimers();
    let unavailable = false;
    const fetcher = vi.fn(async (url: string, _options?: RequestInit) => {
        if (url === '/api/agent/state' && unavailable) throw new Error('Disconnected');
        const data: Record<string, unknown> = {
            '/api/settings': { mode: 'local', paused: false, clock: '2026-10-28T05:00:00Z', frozen_clock: true },
            '/api/version': { version: 'unchanged' }, '/api/runs': [],
            '/api/today': { new_calls: [], attention: [], deadlines_48h: [], date_only: [], uncertain_deadlines: [] },
            '/api/agent/state': { mood: 'needs_decision', status: 'I need a decision.', counts: { decisions: 1, drafts: 0 },
                briefing: [{ text: '1 decision needs your attention.', href: '/work' }],
                decisions: [{ id: 'call-1', title: 'Fictional call', reason: 'Deadline unknown.', action: 'Review deadline', href: '/opportunity/1' }] },
        };
        return { ok: true, json: async () => data[url] };
    });
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter><App /></MemoryRouter>);
    await act(async () => { });
    expect(screen.getByRole('img', { name: 'Scout: Needs decision' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(document.activeElement).toBe(screen.getByLabelText('Ask Scout or give a command'));
    expect(screen.getByLabelText('Ask Scout or give a command').getAttribute('maxlength')).toBe('500');
    fireEvent.keyDown(window, { key: 'Escape' });
    const action = screen.getByRole('link', { name: 'Open all work' });
    expect(document.activeElement).toBe(action);
    unavailable = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(screen.getByRole('img', { name: 'Scout: Disconnected' })).toBeTruthy();
    expect(screen.getByText(/Saved information below may be out of date/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Review deadline' })).toBeTruthy();
    expect(document.activeElement).toBe(action);
    unavailable = false;
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Reconnect' })); });
    expect(screen.getByRole('img', { name: 'Scout: Needs decision' })).toBeTruthy();
    expect(fetcher.mock.calls.every(([, options]) => !(options as RequestInit)?.method)).toBe(true);
});

it('shows Scout disconnected when the service is unavailable on first opening', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Service unavailable')));
    render(<MemoryRouter><App /></MemoryRouter>);
    await act(async () => { });
    expect(screen.getByRole('img', { name: 'Scout: Disconnected' })).toBeTruthy();
    expect(screen.getByText("I can't reach the local service.")).toBeTruthy();
});
