import { useId, useState } from 'react';
import { useDesk } from '../App';
import { DATA_CHANGED, request, useResource } from '../lib/api';
import { categories, date } from '../lib/format';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Failure, mutationReason } from './shared';
import type { LearnedRule, RulePreview, SenderReviewSnapshot } from '../types';

function changed() { window.dispatchEvent(new Event(DATA_CHANGED)); }

export function RuleSuggestion({ rule }: { rule: LearnedRule }) {
    return <div className="notice"><p>I suggested a rule: {rule.title}.</p><p className="meta">{rule.scope}. {rule.match_count} stored messages match. No stored messages were reprocessed.</p><a href={`/memory#rule-${rule.id}`}>Review rule and Undo</a></div>;
}

function RuleCard({ rule, reload }: { rule: LearnedRule; reload: () => void }) {
    const { settings } = useDesk();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [preview, setPreview] = useState<RulePreview & { version: number }>();
    const reason = mutationReason(settings);
    async function action(kind: 'activate' | 'undo' | 'preview' | 'reprocess') {
        setBusy(true); setError(''); setMessage('');
        try {
            if (kind === 'preview') {
                const result = await request<RulePreview>(`/learning/${rule.id}/preview`);
                setPreview({ ...result, version: rule.version });
                return;
            }
            if (kind === 'reprocess') {
                if (!preview) return;
                const result = await request<{ reprocessed: number }>(`/learning/${rule.id}/reprocess`, settings.csrf_token, { expected_version: preview.version, expected_token: preview.token });
                setMessage(`${result.reprocessed} stored messages reprocessed. Manual corrections were preserved.`);
            } else {
                await request(`/learning/${rule.id}`, settings.csrf_token, { action: kind, expected_version: rule.version });
                setMessage(kind === 'undo' ? 'Undone. Future influence is disabled. The original action and past packs remain.' : 'Activated for future use. Stored messages were not reprocessed.');
            }
            setPreview(undefined); reload(); changed();
        } catch (e) { setError(e instanceof Error ? e.message : 'Rule could not be changed.'); }
        finally { setBusy(false); }
    }
    return <article id={`rule-${rule.id}`} className="memory-entry" aria-labelledby={`rule-title-${rule.id}`}>
        <h3 id={`rule-title-${rule.id}`}>{rule.title}</h3>
        <p><strong>{rule.status === 'active' ? 'Active' : rule.status === 'suggested' ? 'Suggested · No influence yet' : 'Undone · No future influence'}</strong></p>
        <p>{rule.scope}</p>
        <p className="meta">{rule.kind === 'sender' ? `${rule.match_count} stored messages match. Manual corrections always win. PS-office trust is unchanged.` : 'Preference fit is separate from decision priority. Urgent deadlines stay first. Unknown source facts do not count as a match.'}</p>
        <p className="meta">Source: {rule.origin_type.replaceAll('_', ' ')} {rule.origin_id && <a href={rule.origin_type === 'message' ? `/work#message-${rule.origin_id}` : `/opportunity/${rule.origin_id}`}>Original action</a>} · Version {rule.version} · Last change {date(rule.changed_at)}</p>
        {rule.conflicts?.map(text => <p className="notice review" key={text}>{text}</p>)}
        <details><summary>Example matches</summary>{rule.examples.length ? <ul>{rule.examples.map(example => <li key={example.message_id}><a href={`/work#message-${example.message_id}`}>{example.subject}</a></li>)}</ul> : <p>No stored example matches.</p>}</details>
        <details><summary>Recent uses</summary>{rule.recent_uses.length ? <ul>{rule.recent_uses.map((use, index) => <li key={index}><a href={`/work#message-${use.message_id}`}>{use.subject}</a> · {date(use.used_at)} · Version {use.version}</li>)}</ul> : <p>No recorded uses yet. Ranking explanations appear beside matching work.</p>}</details>
        <details><summary>Rule versions</summary><ul>{rule.versions.map(version => <li key={version.version}>Version {version.version} · {version.status} · {date(version.changed_at)}</li>)}</ul></details>
        <div className="memory-toolbar">
            {rule.status === 'suggested' && <Button disabled={!!reason || busy} onClick={() => void action('activate')}>Activate rule</Button>}
            {rule.status !== 'undone' && <Button variant="outline" disabled={!!reason || busy} onClick={() => void action('undo')}>{rule.status === 'suggested' ? 'Dismiss suggestion' : 'Undo rule'}</Button>}
            {rule.status === 'active' && rule.kind === 'sender' && <Button variant="outline" disabled={busy} onClick={() => void action('preview')}>Preview stored matches</Button>}
        </div>
        {preview && <div className="notice"><h4>Reprocess stored messages?</h4><p>{preview.match_count} messages match; {preview.eligible_count} can be reprocessed. Manual corrections are excluded. This changes stored categories only; it does not rebuild opportunities or packs.</p><ul>{preview.examples.map(example => <li key={example.message_id}><a href={`/work#message-${example.message_id}`}>{example.subject}</a>{example.manual_correction && ' · Manual correction preserved'}</li>)}</ul><Button disabled={!!reason || busy || !preview.eligible_count} onClick={() => void action('reprocess')}>Confirm reprocessing</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(undefined)}>Cancel reprocessing</Button></div>}
        {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
    </article>;
}

const effects = { prefer_remote: 'Prefer remote roles', prefer_hybrid: 'Prefer hybrid roles', prefer_in_person: 'Prefer in-person roles', avoid_relocation: 'Prefer roles without required relocation' };

export function LearnedRules() {
    const { settings } = useDesk();
    const rules = useResource<{ rules: LearnedRule[] }>('/learning', true);
    const [instruction, setInstruction] = useState('');
    const [effect, setEffect] = useState('prefer_remote');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const id = useId();
    const reason = mutationReason(settings);
    async function save(explicit: boolean) {
        setBusy(true); setError(''); setMessage('');
        try {
            const result = await request<LearnedRule>(`/learning/${explicit ? 'instruction' : 'preference'}`, settings.csrf_token, explicit ? { instruction } : { effect });
            setMessage(result.status === 'active' ? 'Saved locally · Active. Undo is available on the rule.' : 'Scoped preference suggested. Review and activate it below.');
            if (explicit) setInstruction('');
            rules.reload(); changed();
        } catch (e) { setError(e instanceof Error ? e.message : 'Preference could not be saved.'); }
        finally { setBusy(false); }
    }
    return <section className="section" aria-labelledby="memory-learned"><h2 id="memory-learned">Learned rules</h2>
        <p>Rules are visible, versioned and undoable. Undo stops future influence; the original correction, skip reason and past packs remain.</p>
        <p className="meta">Precedence: built-in restrictions, current source evidence, explicit current instructions and preferences, curated memories, then suggested learning. Suggested rules have no effect. Newer preferences win within the same scope; narrower sender rules win over broader ones.</p>
        {reason && <p>{reason}. Rules remain readable.</p>}
        <form className="memory-editor" onSubmit={e => { e.preventDefault(); void save(true); }}>
            <label htmlFor={`${id}-instruction`}>Always or remember instruction</label><Input id={`${id}-instruction`} maxLength={300} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="Remember that I prefer remote roles" />
            <p className="meta">Supported: always prefer remote, hybrid or in-person roles; always avoid relocation. Other prose stays a memory; choose what should generalize using a structured preference.</p>
            <Button type="submit" disabled={!!reason || busy || !instruction.trim()}>Remember preference</Button>
        </form>
        <div className="memory-toolbar"><label htmlFor={`${id}-effect`}>Structured preference</label><select id={`${id}-effect`} value={effect} onChange={e => setEffect(e.target.value)}>{Object.entries(effects).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select><Button variant="outline" disabled={!!reason || busy} onClick={() => void save(false)}>Propose preference</Button></div>
        <p role="status">{message}</p>{error && <p role="alert">{error}</p>}
        {rules.error && <Failure text="Rules could not be loaded." retry={rules.reload} />}
        {!rules.value && !rules.error && <p>Loading learned rules…</p>}
        {rules.value && !(rules.value.rules || []).length && <p>No learned rules yet. Corrections and supported preferences appear here.</p>}
        {(rules.value?.rules || []).map(rule => <RuleCard key={rule.id} rule={rule} reload={rules.reload} />)}
    </section>;
}

function SenderGroup({ group }: { group: SenderReviewSnapshot['groups'][number] }) {
    const { settings } = useDesk();
    const [exampleId, setExampleId] = useState(group.examples[0]?.message_id);
    const [category, setCategory] = useState('research');
    const [condition, setCondition] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [rule, setRule] = useState<LearnedRule>();
    const id = useId();
    const reason = mutationReason(settings);
    const example = group.examples.find(e => e.message_id === exampleId) || group.examples[0];
    async function propose() {
        setBusy(true); setError('');
        try {
            const result = await request<LearnedRule>('/learning/sender', settings.csrf_token, { message_id: example.message_id, category, subject: condition || group.mixed ? example.subject : null });
            setRule(result); changed();
        } catch (e) { setError(e instanceof Error ? e.message : 'Rule could not be proposed.'); }
        finally { setBusy(false); }
    }
    return <article className="memory-entry"><h3>{group.mailbox || 'Sender could not be read'}</h3><p>{group.count} unresolved messages</p>
        <ul>{group.examples.map(e => <li key={e.message_id}><a href={`/work#message-${e.message_id}`}>{e.subject}</a></li>)}</ul>
        {group.mailbox && <form onSubmit={e => { e.preventDefault(); void propose(); }}>
            <label htmlFor={`${id}-example`}>Example for proposed rule</label><select id={`${id}-example`} value={example.message_id} onChange={e => setExampleId(Number(e.target.value))}>{group.examples.map(e => <option key={e.message_id} value={e.message_id}>{e.subject}</option>)}</select>
            <label htmlFor={`${id}-category`}>Proposed category</label><select id={`${id}-category`} value={category} onChange={e => setCategory(e.target.value)}>{Object.entries(categories).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select>
            <label className="check-label"><input type="checkbox" checked={condition || group.mixed} disabled={group.mixed} onChange={e => setCondition(e.target.checked)} />Limit to this exact normalized subject</label>
            <p className="meta">Proposed scope: exact mailbox {group.mailbox}{condition || group.mixed ? `; subject equals ${example.subject}` : '; any subject'}. {group.mixed && 'Different subjects are stored for this sender; a subject condition is required.'}</p>
            <Button type="submit" variant="outline" disabled={!!reason || busy}>Propose sender rule</Button>
        </form>}
        {rule && <RuleSuggestion rule={rule} />}{error && <p role="alert">{error}</p>}
    </article>;
}

export function SenderReview() {
    const review = useResource<SenderReviewSnapshot>('/learning/review', true);
    return <section className="section" aria-labelledby="sender-review"><h2 id="sender-review">Review unfamiliar senders</h2>
        <p>Review examples together and propose an exact sender rule. Activation applies to future mail. Existing messages need a separate preview and confirmation in Memory.</p>
        {review.error && <Failure text="Sender groups could not be loaded." retry={review.reload} />}
        {review.value && <><p role="status">{review.value.unresolved_total} of {review.value.stored_total} messages still need review.</p><p className="meta">A smaller queue does not establish better accuracy. Review the examples against their sources.</p>{review.value.groups?.map(group => <details key={group.mailbox || group.examples[0].message_id}><summary>{group.mailbox || 'Unreadable sender'} · {group.count} need review</summary><SenderGroup group={group} /></details>)}</>}
    </section>;
}
