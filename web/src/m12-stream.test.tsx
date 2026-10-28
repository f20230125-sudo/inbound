import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { Activity, mergeSteps } from './components/activity';
import type { AgentStep } from './types';
import { useLive } from './lib/live';
import { DATA_CHANGED } from './lib/api';

const step = (id: number): AgentStep => ({ id, text: `I recorded step ${id}.`, href: '/settings#runs', occurred_at: '2026-10-28T05:00:00Z', phase: 'committed_result', outcome: 'succeeded', kind: 'snapshot.published' });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('deduplicates overlapping catch-up and SSE IDs and bounds history', () => {
    const result = mergeSteps([step(1), step(2)], [step(2), ...Array.from({ length: 250 }, (_, i) => step(i + 3))]);
    expect(result.length).toBe(100);
    expect(new Set(result.map(s => s.id)).size).toBe(100);
    expect(result.at(-1)?.id).toBe(252);
});

it('resumes after catch-up, batches announcements, preserves focus, and replays with reads only', async () => {
    vi.useFakeTimers();
    const streams: { onmessage: ((event: MessageEvent) => void) | null; close: ReturnType<typeof vi.fn> }[] = [];
    const urls: string[] = [];
    vi.stubGlobal('EventSource', class {
        onmessage = null;
        close = vi.fn();
        constructor(url: string) { urls.push(url); streams.push(this); }
    });
    const fetcher = vi.fn(async (url: string, _options?: RequestInit) => ({ ok: true, json: async () => url.includes('replay=last') ? { steps: [step(1)], label: 'Recorded check - 28 Oct 2026, 09:00 Dubai', after: 1, has_more: false } : { steps: [step(1)], after: 1, has_more: false } }));
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter><Activity /></MemoryRouter>);
    await act(async () => {});
    expect(urls[0]).toBe('/api/agent/stream?after=1');
    const replay = screen.getByRole('button', { name: 'Replay last check' });
    replay.focus();
    await act(async () => {
        for (const id of [2, 2, 3]) streams[0].onmessage?.(new MessageEvent('message', { data: JSON.stringify(step(id)) }));
    });
    expect(screen.getAllByText('I recorded step 2.').length).toBe(1);
    expect(document.activeElement).toBe(replay);
    expect(screen.queryByText('2 new activity steps.')).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
    expect(screen.getByText('2 new activity steps.')).toBeTruthy();
    await act(async () => { fireEvent.click(replay); });
    expect(streams[0].close).toHaveBeenCalled();
    expect(screen.getByText('Recorded check - 28 Oct 2026, 09:00 Dubai')).toBeTruthy();
    expect(screen.queryByText('I recorded step 2.')).toBeNull();
    expect(fetcher.mock.calls.every(([, options]) => !options?.method)).toBe(true);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Return to live activity' })); });
    expect(screen.getByText('I recorded step 3.')).toBeTruthy();
});

it('refreshes open work from committed SSE events once, with version polling still available', async () => {
    vi.useFakeTimers();
    const streams: { onmessage: ((event: MessageEvent) => void) | null }[] = [];
    vi.stubGlobal('EventSource', class {
        onmessage = null; close = vi.fn();
        constructor(_url: string) { streams.push(this); }
    });
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url === '/api/version' ? { version: 'v1' } : url === '/api/agent/steps' ? { steps: [], after: 6 } : { new_calls: [], attention: [], deadlines_48h: [], date_only: [], uncertain_deadlines: [] } })));
    const refresh = vi.fn(async () => {});
    const changed = vi.fn();
    window.addEventListener(DATA_CHANGED, changed);
    function OpenWork() { useLive(refresh, true); return null; }
    const view = render(<OpenWork />);
    await act(async () => {});
    expect(streams.length).toBe(1);
    await act(async () => {
        for (const id of [7, 7]) streams[0].onmessage?.(new MessageEvent('message', { data: JSON.stringify(step(id)) }));
        await vi.advanceTimersByTimeAsync(300);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(changed).toHaveBeenCalledTimes(1);
    view.unmount(); window.removeEventListener(DATA_CHANGED, changed);
});

it('catches up with bounded reads when EventSource is unavailable', async () => {
    vi.useFakeTimers(); vi.stubGlobal('EventSource', undefined);
    let latest = 1;
    const fetcher = vi.fn(async (_url: string) => ({ ok: true, json: async () => ({ steps: [step(latest)], after: latest, has_more: false }) }));
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter><Activity /></MemoryRouter>);
    await act(async () => {});
    expect(screen.getByText('I recorded step 1.')).toBeTruthy();
    latest = 2;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetcher.mock.calls.some(([url]) => url === '/api/agent/steps?after=1')).toBe(true);
    expect(screen.getByText('I recorded step 2.')).toBeTruthy();
});
