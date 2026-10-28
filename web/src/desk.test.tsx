import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { badgeVariant, deadlineText, callTitle } from './lib/format';
import { CopyAnswer, Highlight, PauseControl } from './components/shared';
const now = '2026-10-28T02:30:00+04:00';
it('keeps date-only values free of invented times', () => {
    expect(deadlineText({ status: 'found', normalized: '2026-10-29' }, now).label).toBe('Due 29 Oct 2026 · Time not stated');
});
it('counts timed values in Dubai and distinguishes expiry', () => {
    expect(deadlineText({ status: 'found', normalized: '2026-10-28T12:00:00+04:00' }, now).label).toBe('9 h 30 min left');
    expect(deadlineText({ status: 'found', normalized: '2026-10-28T00:20:00+04:00', past_at_receipt: true }, now).label).toBe('Expired · 2 h 10 min overdue · Deadline passed before receipt');
});
it('never counts down uncertain deadlines', () => {
    expect(deadlineText({ status: 'unknown' }, now).label).toBe('Deadline unknown · Expiry unknown');
    expect(deadlineText({ status: 'conflicting' }, now).label).toBe('Deadline conflicting · No countdown');
});
it('uses semantic badge colours only', () => {
    for (const value of ['New', 'Reviewed', 'Submitted by me', 'Completed', 'Found', 'Paused'])
        expect(badgeVariant(value)).toBe('outline');
    expect(badgeVariant('Passed')).toBe('success');
    expect(badgeVariant('Needs review')).toBe('review');
    expect(badgeVariant('Expired')).toBe('destructive');
});
it('uses effective company, role and city, with a normalized fallback', () => {
    expect(callTitle({ company: 'Ledgercraft', roles: [{ title: 'Backend Intern' }], city: 'Cedar Quay', subject: 'Re: raw' })).toBe('Ledgercraft · Backend Intern · Cedar Quay');
    expect(callTitle({ subject: 'Re: Fwd: Call\u200b  for CV' })).toBe('Call for CV');
});
it('copies the exact approved answer and announces success', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(<CopyAnswer label="Purpose" answer="Approved text." provenance="p1"/>);
    fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }));
    await screen.findByText('Copied');
    expect(writeText).toHaveBeenCalledWith('Approved text.');
});
it('reports clipboard failure and never offers to copy a missing answer', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error()) } });
    const view = render(<CopyAnswer label="Purpose" answer="Exact" provenance="p1"/>);
    fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }));
    await screen.findByText('Could not copy. Select the answer text to copy it.');
    view.rerender(<CopyAnswer label="Challenge / fix" answer="" provenance="p1" needed/>);
    expect(screen.queryByRole('button', { name: 'Copy answer' })).toBeNull();
});
it('does not optimistically change Pause and reports save failures', async () => {
    let reject!: (reason: Error) => void;
    const save = vi.fn(() => new Promise<void>((_, no) => { reject = no; }));
    render(<PauseControl paused={false} replay={false} save={save}/>);
    fireEvent.click(screen.getByRole('button', { name: 'Pause new work' }));
    expect(screen.getByText('Work enabled')).toBeTruthy();
    reject(new Error('failed'));
    expect((await screen.findByRole('alert')).textContent).toBe('Pause could not be saved. Work may still be enabled.');
});
it('Pause can resume while other work is paused and replay cannot mutate', async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const view = render(<PauseControl paused replay={false} save={save} active/>);
    fireEvent.click(screen.getByRole('button', { name: 'Resume work' }));
    expect(save).toHaveBeenCalledWith(false);
    view.rerender(<PauseControl paused replay save={save}/>);
    expect((screen.getByRole('button', { name: 'Resume work' }) as HTMLButtonElement).disabled).toBe(true);
});
it('source text remains literal and highlights only the source quote', () => {
    const { container } = render(<Highlight text={'<script>unsafe()</script> quoted'} quote="quoted"/>);
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('mark')?.textContent).toBe('quoted');
    expect(container.textContent).toContain('<script>unsafe()</script>');
});
