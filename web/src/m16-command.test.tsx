import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { ScoutCommand } from './components/scout-command';

const { refresh } = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('./App', () => ({ useDesk: () => ({ settings: { mode: 'local', csrf_token: 'test', paused: false }, refresh }) }));
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); refresh.mockReset(); });

it('keeps the command input read-only until the confirmed command and its refresh finish', async () => {
    let finish!: () => void;
    refresh.mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) => ({ ok: true, json: async () => ({
        text: options.method === 'POST' ? 'Saved locally.' : 'Confirm this preference.',
        items: [], choices: [], suggestions: [],
        ...(options.method === 'POST' ? {} : { command: { path: '/api/scout/command', ticket: 'fictional' } }),
    }) })));
    render(<MemoryRouter><ScoutCommand returnToWork={() => {}} /></MemoryRouter>);
    const input = screen.getByRole('textbox', { name: 'Ask Scout or give a command' }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Remember that I prefer remote roles' } });
    await act(async () => fireEvent.submit(input.closest('form')!));
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Confirm command' })));
    expect(screen.getByText(/Saved locally/)).toBeTruthy();
    expect(input.readOnly).toBe(true);
    await act(async () => finish());
    expect(input.readOnly).toBe(false);
});
