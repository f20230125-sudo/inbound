import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { ScoutCommand } from './components/scout-command';
import { boundedHistory } from './lib/scout-history';

vi.mock('./App', () => ({ useDesk: () => ({ settings: { mode: 'local', csrf_token: 'test', paused: true }, refresh: vi.fn() }) }));
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

it('asks while paused, keeps commands separate, opens cited evidence and closes with Escape', async () => {
    const calls: RequestInit[] = [];
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) => {
        calls.push(options);
        return { ok: true, json: async () => ({ text: 'Stored project.', items: [{ text: 'Fictional project', citations: [{ entity_type: 'memory', entity_id: 'a', version: 1, label: 'Memory · Project', url: '/api/scout/citation?ticket=one' }] }], choices: [], suggestions: [] }) };
    }));
    render(<MemoryRouter><ScoutCommand returnToWork={() => {}} /></MemoryRouter>);
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = screen.getByRole('textbox', { name: 'Ask Scout or give a command' });
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: 'What do you know about my projects?' } });
    await act(async () => fireEvent.submit(input.closest('form')!));
    expect(screen.getByText(/Stored project\./)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Memory · Project · version 1' })).toBeTruthy();
    expect(calls.every(c => !c.method)).toBe(true);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Conversation with Scout' })).toBeNull();
});

it('bounds local conversation by count and serialized size and drops malformed entries', () => {
    const entries = Array.from({ length: 80 }, () => ({ question: 'x'.repeat(400), reply: { text: 'answer', items: [], choices: [], suggestions: [] } }));
    expect(boundedHistory(entries)).toHaveLength(20);
    expect(JSON.stringify(boundedHistory(entries.map(e => ({ ...e, question: 'x'.repeat(50000) })))).length).toBeLessThanOrEqual(200000);
    expect(boundedHistory([null, {}, { question: '<script>' }])).toEqual([]);
});
