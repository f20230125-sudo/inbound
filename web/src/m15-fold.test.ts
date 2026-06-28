import { describe, expect, it } from 'vitest';
import { foldQuiet } from './components/activity';
import type { AgentStep } from './types';

let id = 0;
function step(kind: string, text: string): AgentStep {
    id += 1;
    return { id, kind, text, href: '/', occurred_at: `2026-10-28T09:${String(id).padStart(2, '0')}:00Z`, phase: 'committed_result', outcome: 'succeeded' };
}
function quietCheck() {
    return [step('gmail.started', 'I started a Gmail check.'), step('gmail.fetched', 'I checked Gmail. No new messages.'), step('gmail.finished', 'I finished this Gmail check.')];
}

describe('foldQuiet', () => {
    it('folds a run of quiet Gmail checks into one row and keeps real work separate', () => {
        const steps = [...quietCheck(), ...quietCheck(), ...quietCheck(),
            step('gmail.fetched', 'I fetched 1 new messages from Gmail.'), step('pack.ready', 'I prepared a draft.'),
            ...quietCheck()];
        const rows = foldQuiet(steps);
        // 3 quiet checks fold to 1 row; 2 real steps; a lone quiet check keeps its 3 steps.
        expect(rows).toHaveLength(6);
        expect('fold' in rows[0] && rows[0].fold.length).toBe(9);
        expect('fold' in rows[1]).toBe(false);
        expect(rows.slice(3).some(row => 'fold' in row)).toBe(false);
    });
});
