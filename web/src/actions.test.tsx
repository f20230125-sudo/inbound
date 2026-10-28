import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CategoryCorrection } from './pages/Today';
import { ReviewActions } from './components/actions';
import type { Message, Opportunity, Pack, Settings } from './types';
let settings: Settings;
vi.mock('./App', () => ({ useDesk: () => ({ settings }) }));
const opportunity = { id: 1, revision_id: 7, status: 'needs_review', fields: { deadline: { status: 'unknown' } }, recommended_role_id: 1, roles: [{ id: 1, title: 'Backend Intern' }] } as unknown as Opportunity;
const pack = { id: 'pack-7', revision_id: 7, provisional: 1, blocker_acknowledged: 0, status: 'needs_review', checks: { passed: true }, selection: { fit: 'low', fit_reason: 'No evidence for 4 of 4 requirements: consider skipping' } } as unknown as Pack;
beforeEach(() => { settings = { mode: 'local', paused: false, csrf_token: 'csrf' } as Settings; });
function show(p = pack) { return render(<ReviewActions opportunity={opportunity} pack={p} active={false} failed={false} reload={vi.fn()} build={vi.fn()}/>); }
it('requires provisional acknowledgement and shows the actual low-fit reason next to Skip', () => {
    show();
    const review = screen.getByRole('button', { name: 'Mark reviewed' }) as HTMLButtonElement;
    expect(review.disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(review.disabled).toBe(false);
    expect(screen.getByText(pack.selection.fit_reason).closest('.skip-area')?.textContent).toContain('Skip');
});
it('blocks stale revision and failed verification without manufacturing pipeline states', () => {
    const view = show({ ...pack, revision_id: 6, provisional: 0 });
    expect((screen.getByRole('button', { name: 'Mark reviewed' }) as HTMLButtonElement).disabled).toBe(true);
    view.rerender(<ReviewActions opportunity={opportunity} pack={{ ...pack, provisional: 0, checks: { passed: false } }} active={false} failed={false} reload={vi.fn()} build={vi.fn()}/>);
    expect((screen.getByRole('button', { name: 'Mark reviewed' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('option', { name: 'Preparing' }) as HTMLOptionElement).disabled).toBe(true);
});
it('keeps copy-independent mutations disabled when paused or in replay', () => {
    settings.paused = true;
    const view = show();
    expect((screen.getByRole('button', { name: 'Build pack' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Resume work to make changes')).toBeTruthy();
    settings = { ...settings, mode: 'replay', paused: false };
    view.rerender(<ReviewActions opportunity={opportunity} pack={pack} active={false} failed={false} reload={vi.fn()} build={vi.fn()}/>);
    expect(screen.getByText('Available in local mode')).toBeTruthy();
});
afterEach(() => vi.unstubAllGlobals());
it('category arrow navigation waits for Enter before writing an override', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ previous_category: 'ps_call' }) });
    vi.stubGlobal('fetch', fetch);
    const done = vi.fn();
    const message = { id: 2, category: 'ps_call', original_category: 'ps_call', classification_history: [] } as unknown as Message;
    render(<CategoryCorrection message={message} done={done}/>);
    const select = screen.getByRole('combobox');
    fireEvent.keyDown(select, { key: 'ArrowDown' });
    fireEvent.change(select, { target: { value: 'ps_admin' } });
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.keyDown(select, { key: 'Enter' });
    await screen.findByText('Category changed to PS administration.');
    expect(done).toHaveBeenCalledWith(2, 'ps_admin');
});
