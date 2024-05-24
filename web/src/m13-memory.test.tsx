import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { SafeMarkdown } from './components/memory-markdown';
import MemoryPage from './pages/Memory';

vi.mock('./App', () => ({ useDesk: () => ({ settings: { mode: 'local', csrf_token: 'test', paused: false } }) }));
afterEach(() => vi.unstubAllGlobals());

it('renders Markdown as inert React nodes, filters unsafe links and never loads images', () => {
    const { container } = render(<SafeMarkdown text={'## Notes\n\n- **Safe** text\n\n<script>alert(1)</script>\n[bad](javascript:alert(1))\n![tracker](https://example.invalid/a.png)\n[Notes](https://example.invalid/notes)\n`<img onerror=alert(1)>`'} />);
    expect(container.querySelector('script,img,iframe,style')).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.getByRole('link', { name: 'Notes' }).getAttribute('href')).toBe('https://example.invalid/notes');
    expect(screen.getByText('Safe').tagName).toBe('STRONG');
    expect(container.textContent).toContain('<script>');
});

const item = { id: 'a'.repeat(32), name: 'Sara', description: 'Fictional profile', type: 'user', content: 'Test profile', origin: 'imported', file: 'memory/sara.md', source: 'synthetic', version: 1, influence: 'remembered', status: 'remembered', changed_at: '2026-10-28T05:00:00Z', conflicts: ['Curated source changed.'], scope: 'Local retrieval only' };
it('shows sections, sources, influence, conflicts and guarded versioned edit/disable/forget controls', async () => {
    const calls: { url: string; body?: Record<string, unknown> }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
        const body = options?.body ? JSON.parse(options.body as string) : undefined;
        calls.push({ url, body });
        return { ok: true, json: async () => ({ version: 1, items: body?.action === 'forget' ? [] : [item], published_at: item.changed_at, error: null }) };
    }));
    render(<MemoryRouter><MemoryPage /></MemoryRouter>);
    await act(async () => {});
    for (const name of ['What I know about you', 'About you', 'Preferences', 'Projects', 'References', 'Learned rules']) expect(screen.getByRole('heading', { name })).toBeTruthy();
    expect(screen.getByText(/Remembered · No active behavior rule/)).toBeTruthy();
    expect(screen.getByText(/memory\/sara.md/)).toBeTruthy();
    expect(screen.getByText('Curated source changed.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sara' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Content' }), { target: { value: 'Edited fictional profile' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save memory' })));
    expect(calls.at(-1)?.body).toMatchObject({ action: 'edit', memory_id: item.id, expected_version: 1, document: { content: 'Edited fictional profile' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Disable Sara' })));
    expect(calls.at(-1)?.body?.action).toBe('disable');
    fireEvent.click(screen.getByRole('button', { name: 'Forget Sara' }));
    expect(screen.getByText(/original curated file remains/i)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Confirm forget' })));
    expect(calls.at(-1)?.body).toMatchObject({ action: 'forget', memory_id: item.id, expected_version: 1 });
    expect(screen.queryByRole('heading', { name: 'Sara' })).toBeNull();
});

it('keeps an open edit intact across a new snapshot and uses its captured version', async () => {
    let version = 1;
    const mutations: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => {
        if (options?.body) { mutations.push(JSON.parse(options.body as string)); return { ok: false, status: 409, json: async () => ({ message: 'Memory changed; refresh before saving' }) }; }
        return { ok: true, json: async () => ({ version, items: [{ ...item, name: `Sara v${version}` }], error: null }) };
    }));
    render(<MemoryRouter><MemoryPage /></MemoryRouter>);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sara v1' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Content' }), { target: { value: 'Unsaved local edit' } });
    version = 2;
    await act(async () => window.dispatchEvent(new Event('inbound-data-changed')));
    expect((screen.getByRole('textbox', { name: 'Content' }) as HTMLTextAreaElement).value).toBe('Unsaved local edit');
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save memory' })));
    expect(mutations[0].expected_version).toBe(1);
    expect(screen.getByRole('alert').textContent).toContain('Memory changed');
});

it('clears an editor when its memory is forgotten in another view', async () => {
    let forgotten = false;
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ version: forgotten ? 2 : 1, items: forgotten ? [] : [item], error: null }) })));
    render(<MemoryRouter><MemoryPage /></MemoryRouter>);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sara' }));
    expect(screen.getByRole('textbox', { name: 'Content' })).toBeTruthy();
    forgotten = true;
    await act(async () => window.dispatchEvent(new Event('inbound-data-changed')));
    expect(screen.queryByRole('textbox', { name: 'Content' })).toBeNull();
});
