import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { LearnedRules, SenderReview } from './components/learning';

vi.mock('./App', () => ({ useDesk: () => ({ settings: { mode: 'local', csrf_token: 'test', paused: false } }) }));
afterEach(() => vi.unstubAllGlobals());

const rule = { id: 'a'.repeat(32), version: 1, status: 'suggested', origin_type: 'message', origin_id: '1', kind: 'sender', mailbox: 'mira@fiction.demo.invalid', subject: 'Studio notes', category: 'research', title: 'Classify Studio notes as Research', scope: 'Exact mailbox and subject', match_count: 2, examples: [{ message_id: 1, subject: 'Studio notes' }], recent_uses: [], versions: [], changed_at: '2026-10-28T05:00:00Z' };

it('shows scope and stored matches before activation, and requires a separate retrospective preview', async () => {
    const mutations: Record<string, unknown>[] = [];
    let active = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
        if (options?.body) { const body = JSON.parse(options.body as string); mutations.push(body); active = body.action === 'activate'; }
        const result = url.endsWith('/preview') ? { match_count: 2, eligible_count: 1, token: 'preview', examples: rule.examples } : { rules: [{ ...rule, status: active ? 'active' : 'suggested', version: active ? 2 : 1 }] };
        return { ok: true, json: async () => result };
    }));
    render(<LearnedRules />);
    await act(async () => {});
    expect(screen.getByText(/2 stored messages match/)).toBeTruthy();
    expect(screen.getByText(/Exact mailbox and subject/)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Activate rule' })));
    expect(mutations).toEqual([{ action: 'activate', expected_version: 1 }]);
    expect(screen.queryByRole('button', { name: 'Confirm reprocessing' })).toBeNull();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Preview stored matches' })));
    expect(screen.getByRole('button', { name: 'Confirm reprocessing' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Undo rule' })).toBeTruthy();
});

it('keeps the unresolved total visible while showing grouped examples and proposed exact scopes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ unresolved_total: 65, stored_total: 295, groups: [{ mailbox: rule.mailbox, count: 3, mixed: true, examples: rule.examples }] }) })));
    render(<SenderReview />);
    await act(async () => {});
    expect(screen.getByText('65 of 295 messages still need review.')).toBeTruthy();
    expect(screen.getByText(rule.mailbox)).toBeTruthy();
    fireEvent.click(screen.getByText(/3 need review/));
    expect(screen.getByRole('link', { name: 'Studio notes' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Propose sender rule' })).toBeTruthy();
});
