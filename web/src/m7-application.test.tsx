import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { OutsideApplicationActions } from './components/actions';
import type { Opportunity, Settings } from './types';

let settings: Settings;
vi.mock('./App', () => ({ useDesk: () => ({ settings }) }));
const opportunity = { id: 1, revision_id: 7, status: 'blocked', outside_application: null } as unknown as Opportunity;
beforeEach(() => { settings = { mode: 'local', paused: false, clock: '2026-10-28T07:59:00+04:00', csrf_token: 'csrf' } as Settings; });
afterEach(() => vi.unstubAllGlobals());

it('requires a checkbox and sends editable applied time, note and local follow-up without a pack', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 1 }) });
    vi.stubGlobal('fetch', fetch);
    const reload = vi.fn();
    render(<OutsideApplicationActions opportunity={opportunity} reload={reload}/>);
    fireEvent.click(screen.getByRole('button', { name: 'I applied outside Inbound' }));
    expect((screen.getByLabelText('Applied at (Dubai time)') as HTMLInputElement).value).toBe('2026-10-28T07:59');
    expect((screen.getByRole('button', { name: 'Record outside application' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox', { name: 'I applied myself outside Inbound' }));
    fireEvent.change(screen.getByLabelText('Applied at (Dubai time)'), { target: { value: '2026-10-27T20:00' } });
    fireEvent.change(screen.getByLabelText('Application note'), { target: { value: 'Used my own CV.' } });
    fireEvent.change(screen.getByLabelText('Follow-up date (local task only)'), { target: { value: '2026-11-02' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record outside application' }));
    await screen.findByText('Outside application saved.');
    expect(reload).toHaveBeenCalled();
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ human_submission: true, applied_at: '2026-10-27T20:00:00+04:00',
        note: 'Used my own CV.', follow_up: '2026-11-02', expected_revision_id: 7, expected_content_version: 0, expected_activity_id: null });
});

it.each(['paused', 'replay'])('disables the outside declaration while %s', state => {
    settings = { ...settings, paused: state === 'paused', mode: state === 'replay' ? 'replay' : 'local' };
    render(<OutsideApplicationActions opportunity={opportunity} reload={vi.fn()}/>);
    expect((screen.getByRole('button', { name: 'I applied outside Inbound' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(state === 'paused' ? 'Resume work to make changes' : 'Available in local mode')).toBeTruthy();
});

it('labels the prefilled note for a correction independently of its previous contents', () => {
    const op = { ...opportunity, outside_application: { id: 4, applied_at: settings.clock,
        recorded_at: settings.clock, note: 'Previous application note', follow_up: null, previous_activity_id: null } };
    render(<OutsideApplicationActions opportunity={op} reload={vi.fn()}/>);
    fireEvent.click(screen.getByRole('button', { name: 'Correct outside application' }));
    expect((screen.getByLabelText('Application note', { exact: true }) as HTMLTextAreaElement).value).toBe('Previous application note');
});
