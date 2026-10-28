import { Link } from 'react-router';
import type { ScoutMood } from '../types';

// The dispatch slip is code-native, monochrome and still. Each expression follows a fact.
export const expressions = {
    idle: { label: 'Idle', eyes: 'M29 37h7 M53 37h7', brow: 'M28 29h9 M52 29h9', mouth: 'M36 53q9 3 18 0' },
    working: { label: 'Working', eyes: 'M29 38h7 M53 38h7', brow: 'M28 29l9 4 M52 33l9-4', mouth: 'M38 54h14' },
    needs_decision: { label: 'Needs decision', eyes: 'M32 37v3 M56 37v3', brow: 'M28 26l9-3 M52 30h9', mouth: 'M38 54h14' },
    draft_ready: { label: 'Draft ready', eyes: 'M29 37h7 M53 37h7', brow: 'M28 29h9 M52 29h9', mouth: 'M35 51q10 12 20 0' },
    failed: { label: 'Failed', eyes: 'M32 38v3 M56 38v3', brow: 'M28 32l9-5 M52 27l9 5', mouth: 'M36 57q9-8 18 0' },
    paused: { label: 'Paused', eyes: 'M28 39q5 5 10 0 M51 39q5 5 10 0', brow: 'M28 30h9 M52 30h9', mouth: 'M39 54h12' },
    disconnected: { label: 'Disconnected', eyes: 'M29 38h7 M53 38h7', brow: 'M28 29h9 M52 29h9', mouth: 'M39 54h12' },
} as const;

export function ScoutFace({ mood }: { mood: ScoutMood }) {
    const expression = expressions[mood];
    return <svg className="scout-face" viewBox="0 0 90 100" role="img" aria-label={`Scout: ${expression.label}`} data-mood={mood}>
        <path d="M8 3h60l14 14v79H8Z M68 3v15h14" fill="var(--card)" stroke="currentColor" strokeWidth="2" />
        <g fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d={expression.brow} /><path d={expression.eyes} /><path d={expression.mouth} />
            <path d="M19 79h28 M19 86h17" strokeWidth="1.5" />
            {mood === 'disconnected' && <path d="M58 77l13 13 M58 90l13-13" />}
        </g>
    </svg>;
}

export function Briefing({ clauses }: { clauses: { text: string; href: string }[] }) {
    return <div className="scout-briefing">{clauses.map(clause => <p key={clause.text}><Link to={clause.href}>{clause.text}</Link></p>)}</div>;
}
