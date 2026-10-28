import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router';
import { useDesk } from '../App';
import { DATA_CHANGED, request, useResource } from '../lib/api';
import { categories, date, deadlineGroup, fieldValue, label, normalizeSubject, opportunityTitle, statuses } from '../lib/format';
import type { Entry, LearnedRule, Message, Opportunity, Today } from '../types';
import { RuleSuggestion, SenderReview } from '../components/learning';
import { MessageSource } from '../components/message-source';
import { OutsideApplicationStatus } from '../components/actions';
import { Button } from '../components/ui/button';
import { DeadlineDisplay, Failure, Loading, Section, SnapshotBanner, StatusBadge } from '../components/shared';
function remember(id: string) { sessionStorage.setItem('inbound-inbox-query', window.location.search); sessionStorage.setItem('inbound-inbox-scroll', String(window.scrollY)); sessionStorage.setItem('inbound-inbox-focus', id); }
export function AdminNotice({ entry, now }: {
    entry: Entry;
    now: string;
}) { return <><p className="meta">PS administration · {entry.provider_id}</p><strong>{entry.display_title}</strong>{entry.deadline && <DeadlineDisplay record={entry.deadline} now={now} admin/>}<a href={`#message-${entry.id}`}>View source</a></>; }
export function AttentionList({ title, entries, now, empty }: {
    title: string;
    entries: Entry[];
    now: string;
    empty: string;
}) {
    const [expanded, setExpanded] = useState(false);
    return <Section title={title}><ul className={`summary-list ${expanded ? 'expanded' : ''}`}>{entries.map((entry, index) => <li key={`${entry.kind}-${entry.id}`} className={`summary-item ${index >= 3 ? 'extra' : ''} ${entry.deadline_group === 'overdue' ? 'expired-row' : ''}`} data-case={entry.provider_id}>{entry.kind === 'ps_admin' ? <AdminNotice entry={entry} now={now}/> : <><p className="meta">Call · {entry.provider_id}</p><strong>{entry.display_title}</strong>{['Needs your decision', 'Past deadlines'].includes(title) && <p className={entry.deadline_group === 'overdue' ? 'past' : 'review'}>{entry.attention_reason}</p>}<DeadlineDisplay record={entry.deadline} now={now}/><>{entry.preference_reasons?.map(reason => <p className="meta" key={reason.rule_id}><a href={reason.href}>{reason.text}</a> · {reason.evidence} · {reason.score > 0 ? "+" : ""}{reason.score} preference fit; deadline priority unchanged.</p>)}</><p className="meta">{entry.mode && label(entry.mode)} {entry.stipend != null && `· ${fieldValue(entry.stipend)}`}</p><Link id={`summary-${title}-${entry.id}`} to={`/opportunity/${entry.id}`} onClick={() => remember(`summary-${title}-${entry.id}`)}>Open opportunity</Link></>}</li>)}</ul>{!entries.length ? <p>{empty}</p> : <Button variant="outline" onClick={() => setExpanded(v => !v)} aria-expanded={expanded}>{expanded ? 'Show fewer' : `View all (${entries.length})`}</Button>}</Section>;
}
export function CategoryCorrection({ message, done }: {
    message: Message;
    done: (id: number, category: string) => void;
}) {
    const { settings } = useDesk();
    const [draft, setDraft] = useState(message.category);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(false);
    const [saved, setSaved] = useState('');
    const [previous, setPrevious] = useState<string>();
    const [rule, setRule] = useState<LearnedRule>();
    const [events, setEvents] = useState<{
        category: string;
        created_at: string;
    }[]>([]);
    const keyboard = useRef(false);
    useEffect(() => setDraft(message.category), [message.category]);
    async function save(category: string) {
        if (category === message.category)
            return;
        setBusy(true);
        setError(false);
        try {
            const result = await request<{
                previous_category: string; learning_rule: LearnedRule | null;
            }>(`/messages/${message.id}/category`, settings.csrf_token, { category });
            setEvents(v => [...v, { category, created_at: new Date().toISOString() }]);
            setPrevious(result.previous_category);
            setRule(result.learning_rule || undefined);
            window.dispatchEvent(new Event(DATA_CHANGED));
            setSaved(`Category changed to ${label(category)}.`);
            done(message.id, category);
        }
        catch {
            setError(true);
            setDraft(message.category);
        }
        finally {
            setBusy(false);
        }
    }
    const blocked = settings.mode === 'replay' ? 'Category changes are available in local mode.' : settings.paused ? 'Resume work to change categories.' : '';
    return <div className="category-correction"><label>Correct category<select value={draft} disabled={!!blocked || busy} onPointerDown={() => { keyboard.current = false; }} onKeyDown={e => { if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key))
        keyboard.current = true; if (e.key === 'Enter') {
        keyboard.current = false;
        void save(draft);
    } }} onChange={e => { setDraft(e.target.value); if (!keyboard.current)
        void save(e.target.value); }} onBlur={() => { keyboard.current = false; setDraft(message.category); }}>{Object.entries(categories).map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select></label>{blocked && <p>{blocked}</p>}{saved && <p role="status">{saved} <Button variant="outline" disabled={!!blocked || busy} onClick={() => previous && void save(previous)}>Undo</Button></p>}{error && <p role="alert">Category was not changed. Retry.</p>}{rule && <RuleSuggestion rule={rule} />}<details><summary>Classification history</summary><p>Original: {label(message.original_category)} · {message.rule_id}</p><p>{message.reason}</p><p>{message.source_quote}</p>{[...message.classification_history, ...events].map((h, i) => <p key={i}>{label(h.category)} · {date(h.created_at)}</p>)}</details></div>;
}
export function MessageCard({ message, op, done }: {
    message: Message;
    op?: Opportunity;
    done: (id: number, category: string) => void;
}) {
    const { settings } = useDesk();
    const [source, setSource] = useState(false);
    const title = op ? opportunityTitle(op) : normalizeSubject(message.subject);
    const deadline = op?.fields.deadline || message.fields.admin_deadline;
    return <article className="message-card" id={`message-${message.id}`} data-case={message.provider_id}><div className="message-main"><div><h3>{op ? <Link id={`message-link-${message.id}`} to={`/opportunity/${op.id}`} onClick={() => remember(`message-link-${message.id}`)}>{title}</Link> : <a href={`#source-${message.id}`} onClick={e => { e.preventDefault(); setSource(v => !v); }} aria-expanded={source}>{title}</a>}</h3><p className="meta">{message.provider_id} · {message.sender} · {message.attachment_count} attachments</p></div><div><span className="mobile-label">Category</span><StatusBadge value={message.category}/>{message.corrected_category && <p className="meta">Manual override</p>}<p><span className="mobile-label">Received: </span>{date(message.received_at)}</p></div></div><div className="message-detail"><div><p className="mobile-label">Why</p><p>{message.provider_id === 'J06' ? 'No exact PS-office sender match.' : message.reason}</p><p className="quote">Source: {message.source_quote === message.sender ? 'From' : message.subject.includes(message.source_quote) ? 'subject' : 'body'} · “{message.source_quote}”</p><p className="meta">Rule: {message.rule_id}</p><MessageSource message={message} open={source} onOpenChange={setSource} /></div><div><p className="mobile-label">Deadline / call</p>{deadline ? <DeadlineDisplay record={deadline} now={settings.clock} admin={message.category === 'ps_admin'}/> : <p>Not applicable</p>}{op && <><OutsideApplicationStatus activity={op.outside_application}/><p><StatusBadge value={op.status}/></p><Link to={`/opportunity/${op.id}`} onClick={() => remember(`message-link-${message.id}`)}>Open opportunity</Link></>}</div><CategoryCorrection message={message} done={done}/></div></article>;
}
export function MessageRow({ message, op, done }: {
    message: Message;
    op?: Opportunity;
    done: (id: number, category: string) => void;
}) {
    const { settings } = useDesk();
    const [source, setSource] = useState(false);
    const title = op ? opportunityTitle(op) : normalizeSubject(message.subject);
    const deadline = op?.fields.deadline || message.fields.admin_deadline;
    return <tr id={`message-${message.id}`} data-case={message.provider_id}><td><strong>{op ? <Link id={`message-link-${message.id}`} to={`/opportunity/${op.id}`} onClick={() => remember(`message-link-${message.id}`)}>{title}</Link> : <a href={`#source-${message.id}`} onClick={e => { e.preventDefault(); setSource(v => !v); }} aria-expanded={source}>{title}</a>}</strong><p>{message.sender}</p><p className="meta">{message.provider_id} · {message.attachment_count} attachments</p></td><td>{date(message.received_at)}</td><td><StatusBadge value={message.category}/>{message.corrected_category && <p>Manual override</p>}</td><td><p>{message.provider_id === 'J06' ? 'No exact PS-office sender match.' : message.reason}</p><p className="quote">Source: {message.source_quote === message.sender ? 'From' : message.subject.includes(message.source_quote) ? 'subject' : 'body'} · “{message.source_quote}”</p><p className="meta">Rule: {message.rule_id}</p><MessageSource message={message} open={source} onOpenChange={setSource} /></td><td>{deadline ? <DeadlineDisplay record={deadline} now={settings.clock} admin={message.category === 'ps_admin'}/> : <p>Not applicable</p>}{op && <><OutsideApplicationStatus activity={op.outside_application}/><StatusBadge value={op.status}/><p><Link to={`/opportunity/${op.id}`}>Open opportunity</Link></p></>}</td><td><CategoryCorrection message={message} done={done}/></td></tr>;
}
export default function TodayPage() {
    const { settings } = useDesk();
    const summary = useResource<Today>('/today', true);
    useEffect(() => {
        const visible = () => { if (!document.hidden) summary.reload(); };
        const timer = window.setInterval(visible, 60000);
        document.addEventListener('visibilitychange', visible);
        return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
    }, [summary.reload]);
    const inbox = useResource<Message[]>('/messages');
    const calls = useResource<Opportunity[]>('/opportunities');
    const [corrections, setCorrections] = useState<Record<number, string>>({});
    const [announcement, setAnnouncement] = useState('');
    const [mobile, setMobile] = useState(() => window.innerWidth <= 700);
    useEffect(() => { const resize = () => setMobile(window.innerWidth <= 700); window.addEventListener('resize', resize); return () => window.removeEventListener('resize', resize); }, []);
    const [params, setParams] = useSearchParams();
    const location = useLocation();
    const sourceTarget = /^#message-\d+$/.test(location.hash);
    const expanded = params.get('all') === '1' || sourceTarget;
    useEffect(() => { sessionStorage.setItem('inbound-inbox-query', params.size ? `?${params}` : ''); }, [params]);
    const category = params.get('category') || '';
    const attention = params.get('attention') || '';
    const status = params.get('status') || '';
    const sort = params.get('sort') || '';
    const ops = useMemo(() => new Map(calls.value?.map(o => [o.id, o])), [calls.value]);
    const all = useMemo(() => (inbox.value || []).map(m => corrections[m.id] ? { ...m, category: corrections[m.id], corrected_category: corrections[m.id] } : m), [inbox.value, corrections]);
    const filtered = all.filter(m => {
        const op = m.opportunity_id ? ops.get(m.opportunity_id) : undefined;
        const dl = op?.fields.deadline || m.fields.admin_deadline;
        const group = deadlineGroup(dl, settings.clock);
        const timed = dl?.normalized && typeof dl.normalized === 'string' && dl.normalized.length > 10 ? new Date(dl.normalized).getTime() - new Date(settings.clock).getTime() : undefined;
        const review = m.category === 'needs_review' || op?.status === 'blocked' || Object.values(op?.fields || {}).some(f => f.status === 'conflicting');
        return (!category || m.category === category) && (!status || op?.status === status) && (!attention || attention === 'due' && timed !== undefined && group === 0 && timed > 0 && timed <= 48 * 3600000 || attention === 'overdue' && group === 2 || attention === 'review' && review || attention === 'corrected' && !!m.corrected_category);
    }).sort((a, b) => {
        const da = ops.get(a.opportunity_id || 0)?.fields.deadline || a.fields.admin_deadline;
        const db = ops.get(b.opportunity_id || 0)?.fields.deadline || b.fields.admin_deadline;
        const newest = new Date(b.received_at).getTime() - new Date(a.received_at).getTime() || a.id - b.id;
        if (sort === 'oldest')
            return new Date(a.received_at).getTime() - new Date(b.received_at).getTime() || a.id - b.id;
        if (sort === 'deadline')
            return deadlineGroup(da, settings.clock) - deadlineGroup(db, settings.clock) || String(da?.normalized || '').localeCompare(String(db?.normalized || '')) || a.id - b.id;
        if (sort === 'review') {
            const rank = (m: Message) => { const op = ops.get(m.opportunity_id || 0); return op?.blocked_reason || Object.values(op?.fields || {}).some(f => f.status === 'conflicting') ? 0 : m.category === 'needs_review' ? 1 : 2; };
            return rank(a) - rank(b) || newest;
        }
        return newest;
    });
    const visible = expanded ? filtered : filtered.slice(0, 25);
    function filter(key: string, value: string) { setParams(previous => { const next = new URLSearchParams(previous); next.delete('all'); if (value)
        next.set(key, value);
    else
        next.delete(key); return next; }, { replace: true }); }
    function done(id: number, value: string) {
        const index = filtered.findIndex(m => m.id === id);
        setCorrections(v => ({ ...v, [id]: value }));
        if (category && category !== value) {
            setAnnouncement(`Category changed to ${label(value)}. Message no longer matches these filters.`);
            window.setTimeout(() => { const next = filtered[index + 1] || filtered[index - 1]; (document.getElementById(`message-link-${next?.id}`) || document.getElementById('inbox'))?.focus(); }, 0);
        }
    }
    return <>{summary.error ? <Failure text="Today could not be loaded." retry={summary.reload}/> : !summary.value ? <Loading text="Loading Today and Inbox…"/> : <><SnapshotBanner snapshot={summary.value.snapshot}/>{!all.length && inbox.value && <Section title="No messages imported."><p>Import an export folder or EML folder to start.</p>{settings.mode === 'local' && <Link to="/settings#import">Import messages</Link>}</Section>}<div className="summary-grid"><AttentionList title="Deadlines within 48 hours" entries={summary.value.deadlines_48h} now={settings.clock} empty="No supported deadlines within the next 48 hours."/><AttentionList title="New calls" entries={summary.value.new_calls.filter(e => deadlineGroup(e.deadline, settings.clock) !== 2)} now={settings.clock} empty="No new calls in this snapshot."/><AttentionList title="PS administration" entries={summary.value.admin_tasks.filter(e => deadlineGroup(e.deadline, settings.clock) !== 2)} now={settings.clock} empty="No PS administration notices in this snapshot."/></div><AttentionList title="Needs your decision" entries={(summary.value.decision_queue || summary.value.attention).filter(e => deadlineGroup(e.deadline, settings.clock) !== 2)} now={settings.clock} empty="No active decisions."/><AttentionList title="Date-only deadlines" entries={summary.value.date_only} now={settings.clock} empty="No date-only deadlines today or tomorrow."/><AttentionList title="Unknown / conflicting deadlines" entries={summary.value.uncertain_deadlines} now={settings.clock} empty="No uncertain deadlines."/><details id="past-deadlines"><summary>Past deadlines</summary><AttentionList title="Past deadlines" entries={summary.value.past_deadlines || summary.value.attention.filter(e => deadlineGroup(e.deadline, settings.clock) === 2)} now={settings.clock} empty="No past deadlines."/></details><Section title="Outside applications / follow-ups">{summary.value.outside_applications?.length ? <ul>{summary.value.outside_applications.map(entry => <li key={entry.id}><Link to={`/opportunity/${entry.id}`}>{entry.display_title}</Link><OutsideApplicationStatus activity={entry.outside_application}/></li>)}</ul> : <p>No outside applications recorded.</p>}</Section></>}<SenderReview /><Section title="Inbox" id="inbox"><div className="filters">{[
            ['category', 'Category:', category, { '': 'All categories', ...categories }],
            ['attention', 'Attention:', attention, { '': 'All messages', due: 'Due within 48 hours', overdue: 'Overdue', review: 'Needs review', corrected: 'Corrected' }],
            ['status', 'Application status:', status, { '': 'All statuses', ...statuses }],
            ['sort', 'Sort:', sort, { '': 'Newest first', oldest: 'Oldest first', deadline: 'Earliest deadline', review: 'Needs review first' }],
        ].map(([key, text, value, options]) => <label key={String(key)}>{String(text)}<select aria-label={String(text)} value={String(value)} onChange={e => filter(String(key), e.target.value)}>{Object.entries(options).map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>)}<Button variant="outline" onClick={() => setParams({})}>Clear filters</Button></div><p role="status">{announcement}</p>{inbox.error || calls.error ? <Failure text="Inbox could not be loaded." retry={() => { inbox.reload(); calls.reload(); }}/> : !inbox.value || !calls.value ? <Loading text="Loading Today and Inbox…"/> : !filtered.length ? <p>No messages match these filters.</p> : <>{mobile ? <>{visible.map((m, i) => <div key={m.id}>{sort === 'deadline' && (i === 0 || deadlineGroup(ops.get(visible[i - 1].opportunity_id || 0)?.fields.deadline || visible[i - 1].fields.admin_deadline, settings.clock) !== deadlineGroup(ops.get(m.opportunity_id || 0)?.fields.deadline || m.fields.admin_deadline, settings.clock)) && <h3>{['Supported upcoming timed deadlines', 'Date-only deadlines', 'Overdue deadlines', 'Unknown / conflicting / not applicable'][deadlineGroup(ops.get(m.opportunity_id || 0)?.fields.deadline || m.fields.admin_deadline, settings.clock)]}</h3>}<MessageCard message={m} op={ops.get(m.opportunity_id || 0)} done={done}/></div>)}</> : <div className="inbox-table"><table><caption>Triaged inbox</caption><thead><tr>{['Message', 'Received', 'Category', 'Why', 'Deadline / call', 'Correct category'].map(t => <th scope="col" key={t}>{t}</th>)}</tr></thead><tbody>{visible.map((m, i) => <Fragment key={m.id}>{sort === 'deadline' && (i === 0 || deadlineGroup(ops.get(visible[i - 1].opportunity_id || 0)?.fields.deadline || visible[i - 1].fields.admin_deadline, settings.clock) !== deadlineGroup(ops.get(m.opportunity_id || 0)?.fields.deadline || m.fields.admin_deadline, settings.clock)) && <tr><th colSpan={6} scope="rowgroup">{['Supported upcoming timed deadlines', 'Date-only deadlines', 'Overdue deadlines', 'Unknown / conflicting / not applicable'][deadlineGroup(ops.get(m.opportunity_id || 0)?.fields.deadline || m.fields.admin_deadline, settings.clock)]}</th></tr>}<MessageRow message={m} op={ops.get(m.opportunity_id || 0)} done={done}/></Fragment>)}</tbody></table></div>}{filtered.length > 25 && <Button variant="outline" aria-expanded={expanded} onClick={() => { const next = new URLSearchParams(params); if (expanded) next.delete('all'); else next.set('all', '1'); setParams(next, { replace: true }); }}>{expanded ? 'Show fewer messages' : `Show all ${filtered.length}`}</Button>}<p className="meta">Showing {visible.length} of {filtered.length} messages</p></>}</Section></>;
}
