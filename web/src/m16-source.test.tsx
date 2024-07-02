import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MessageSource } from './components/message-source';
import { DATA_CHANGED } from './lib/api';
import type { Message } from './types';

const message = { id: 7, provider_id: 'fictional', subject: 'Studio notes', sender: 'mira@fiction.demo.invalid', sent_at: '2026-10-28T05:00:00Z', source_quote: 'Fictional body' } as Message;
afterEach(() => vi.unstubAllGlobals());

it('fetches only when opened, retains source across live summaries, and reuses it on reopening', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ ...message, body_text: 'Fictional body <script>inert</script>' }) }));
    vi.stubGlobal('fetch', fetch);
    const { rerender } = render(<MessageSource message={message} open={false} onOpenChange={() => {}} />);
    expect(fetch).not.toHaveBeenCalled();
    rerender(<MessageSource message={message} open onOpenChange={() => {}} />);
    await act(async () => {});
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/api/messages/7', expect.anything());
    expect(screen.getByText(/<script>inert<\/script>/)).toBeTruthy();
    await act(async () => window.dispatchEvent(new Event(DATA_CHANGED)));
    rerender(<MessageSource message={{ ...message }} open={false} onOpenChange={() => {}} />);
    rerender(<MessageSource message={{ ...message }} open onOpenChange={() => {}} />);
    await act(async () => {});
    expect(fetch).toHaveBeenCalledTimes(1);
});

it('shows an accessible failure and retries a failed source read', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error('local failure')).mockResolvedValue({ ok: true, json: async () => ({ ...message, body_text: 'Recovered fictional body' }) });
    vi.stubGlobal('fetch', fetch);
    render(<MessageSource message={message} open onOpenChange={() => {}} />);
    await act(async () => {});
    expect(screen.getByRole('alert').textContent).toContain('Source could not be loaded');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await act(async () => {});
    expect(screen.getByText(/Recovered fictional body/)).toBeTruthy();
});
