import { describe, expect, it } from 'vitest';
import { alertsFor } from './lib/live';
import type { Entry, Today } from './types';

const now = new Date('2026-10-28T02:00:00Z'); // 06:00 Dubai
function entry(id: number, deadline: string | null, extra: Partial<Entry> = {}): Entry {
    return {
        id, kind: 'ps_call', display_title: `Call ${id}`, subject: '', provider_id: `p${id}`,
        deadline: deadline ? { name: 'deadline', raw: '', normalized: deadline, status: 'found', source_text: '' } as unknown as Entry['deadline'] : null,
        deadline_group: '', deadline_label: '08:00', attention_reason: '', ...extra,
    };
}
function today(parts: Partial<Today>): Today {
    return { now: now.toISOString(), snapshot: { imported_at: null, latest_message_at: null, stale: false, version: 1, latest_import_failure: null },
        decision_queue: [], past_deadlines: [], attention: [], deadlines_48h: [], date_only: [], uncertain_deadlines: [], new_calls: [], admin_tasks: [], ...parts };
}

describe('alertsFor', () => {
    it('treats a call first seen in any Today list as new (it may already be blocked or drafted)', () => {
        const value = today({ attention: [entry(8, null, { status: 'blocked' })] });
        expect(alertsFor(value, now, []).map(a => a.key)).toEqual(['new:8']);
    });
    it('alerts once for a new PS call and never for admin notices', () => {
        const value = today({ new_calls: [entry(1, null), entry(2, null, { kind: 'ps_admin' })] });
        expect(alertsFor(value, now, []).map(a => a.key)).toEqual(['new:1']);
        expect(alertsFor(value, now, ['new:1'])).toEqual([]);
    });
    it('alerts for a timed deadline within 12 hours that is not applied or skipped', () => {
        const value = today({
            deadlines_48h: [
                entry(3, '2026-10-28T08:00:00+04:00'),
                entry(4, '2026-10-29T08:00:00+04:00'),
                entry(5, '2026-10-28T08:00:00+04:00', { status: 'skipped' }),
                entry(6, '2026-10-28'),
                entry(7, '2026-10-28T08:00:00+04:00'),
            ],
            outside_applications: [{ id: 7, display_title: 'Call 7', outside_application: {} as never }],
        });
        const keys = alertsFor(value, now, []).map(a => a.key);
        expect(keys.filter(k => k.startsWith('due12:'))).toEqual(['due12:3:2026-10-28T08:00:00+04:00']);
        // An amended deadline is a new alert; the old one stays deduplicated.
        const amended = today({ deadlines_48h: [entry(3, '2026-10-28T09:00:00+04:00')] });
        expect(alertsFor(amended, now, keys).map(a => a.key)).toEqual(['due12:3:2026-10-28T09:00:00+04:00']);
    });
});
