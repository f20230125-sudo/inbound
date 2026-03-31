import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AttachmentRecovery } from './components/attachment-recovery';
import type { Opportunity, Settings } from './types';

let settings: Settings;
vi.mock('./App', () => ({ useDesk: () => ({ settings }) }));
const opportunity = { id: 1, revision_id: 7, content_version: 0, blocked_reason: 'JD.pdf missing' } as Opportunity;
const attachment = { id: 2, filename: 'JD.pdf' } as NonNullable<Opportunity['attachments']>[number];
const preview = { text: '<script>plain text only</script>', roles: [{ title: 'Backend Intern', requirements: [{ text: 'SQL' }] }],
    content_hash: 'hash', expected_revision_id: 7, expected_content_version: 0, preview_token: 'signed', parse_status: 'parsed' };
beforeEach(() => { settings = { mode: 'local', paused: false, csrf_token: 'csrf' } as Settings; });
afterEach(() => vi.unstubAllGlobals());

function choose() {
    fireEvent.click(screen.getByRole('button', { name: 'Attach the JD file' }));
    fireEvent.change(screen.getByLabelText('JD file for JD.pdf'), { target: { files: [new File(['%PDF-1.7'], 'new.pdf', { type: 'application/pdf' })] } });
}

it('previews plain text before explicit confirm and resends the exact file with preview versions', async () => {
    const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => preview })
        .mockResolvedValueOnce({ ok: true, json: async () => ({ parse_status: 'parsed' }) });
    vi.stubGlobal('fetch', fetch);
    const reload = vi.fn();
    render(<AttachmentRecovery opportunity={opportunity} attachment={attachment} reload={reload}/>);
    choose();
    await screen.findByText(preview.text);
    expect(screen.getByText('Backend Intern')).toBeTruthy();
    expect(document.querySelector('script')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Use this file for JD.pdf' }));
    await screen.findByText('JD file attached. Requirements and coverage updated. Build a new pack to review it.');
    expect(reload).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[1];
    expect(url).toBe('/api/opportunities/1/attachments/confirm');
    expect(options.body.get('content_hash')).toBe('hash');
    expect(options.body.get('expected_content_version')).toBe('0');
    expect(options.body.get('attachment_id')).toBe('2');
    expect(options.body.get('file').name).toBe('new.pdf');
    expect(options.headers['X-CSRF-Token']).toBe('csrf');
    expect(options.headers['Content-Type']).toBeUndefined();
});

it('announces unreadable previews and never offers confirmation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...preview,
        parse_status: 'unreadable', reason: 'No extractable text', text: '', roles: [] }) }));
    render(<AttachmentRecovery opportunity={opportunity} attachment={attachment} reload={vi.fn()}/>);
    choose();
    expect((await screen.findByRole('alert')).textContent).toContain('No extractable text');
    expect(screen.queryByRole('button', { name: 'Use this file for JD.pdf' })).toBeNull();
});

it('announces stale confirmation and requires a fresh preview', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => preview })
        .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ message: 'Call changed; preview again' }) }));
    render(<AttachmentRecovery opportunity={opportunity} attachment={attachment} reload={vi.fn()}/>);
    choose();
    fireEvent.click(await screen.findByRole('button', { name: 'Use this file for JD.pdf' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Call changed');
    expect(screen.queryByRole('button', { name: 'Use this file for JD.pdf' })).toBeNull();
});

it.each(['pause', 'replay'])('disables file recovery under %s', guard => {
    settings = { ...settings, paused: guard === 'pause', mode: guard === 'replay' ? 'replay' : 'local' };
    render(<AttachmentRecovery opportunity={opportunity} attachment={attachment} reload={vi.fn()}/>);
    expect((screen.getByRole('button', { name: 'Attach the JD file' }) as HTMLButtonElement).disabled).toBe(true);
});
