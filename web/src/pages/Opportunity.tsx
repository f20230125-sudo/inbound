import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useDesk } from '../App';
import { request, useResource } from '../lib/api';
import { date, fieldValue } from '../lib/format';
import type { Field, Opportunity, Pack, Run } from '../types';
import { DeadlineDisplay, Failure, Loading, Section, StatusBadge } from '../components/shared';
import { AttachmentBlocker, Facts, RevisionHistory, RoleCoverage } from '../components/facts';
import { FormAnswers, PackPreview, ProjectSelection, VerificationList } from '../components/pack';
import { ReviewActions } from '../components/actions';
function ExternalLink({ field, title }: {
    field?: Field;
    title: string;
}) {
    const { settings } = useDesk();
    if (!field || !['found', 'inferred'].includes(field.status) || typeof field.normalized !== 'string')
        return <p>{title}: Unknown / conflicting</p>;
    let url: URL;
    try {
        url = new URL(field.normalized);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password)
            return null;
    }
    catch {
        return null;
    }
    return settings.mode === 'replay' ? <p>{title} · {url.hostname} · Synthetic link — not opened in replay</p> : <p><a href={url.href} target="_blank" rel="noopener noreferrer">{title}</a> · {url.hostname} · Opens in a new tab</p>;
}
export default function OpportunityPage() {
    const { id } = useParams();
    if (!id)
        return <p>Choose a call from Today / Inbox · <Link to="/">Today / Inbox</Link></p>;
    return <OpportunityDetail key={id} id={id}/>;
}
function OpportunityDetail({ id }: {
    id: string;
}) {
    const { settings } = useDesk();
    const resource = useResource<Opportunity>(`/opportunities/${id}`);
    const [pack, setPack] = useState<Pack>();
    const [packError, setPackError] = useState(false);
    const [loadingPack, setLoadingPack] = useState(false);
    const [runId, setRunId] = useState<number>();
    const [active, setActive] = useState(false);
    const [lastRun, setLastRun] = useState<number>();
    const [failed, setFailed] = useState(false);
    const [pollError, setPollError] = useState(false);
    const op = resource.value;
    const currentPack = op?.packs?.[0];
    useEffect(() => {
        setPack(undefined);
        setPackError(false);
        if (!currentPack || currentPack.revision_id !== op?.revision_id || !['needs_review', 'reviewed', 'submitted_by_me'].includes(currentPack.status)) {
            setLoadingPack(false);
            return;
        }
        let alive = true;
        setLoadingPack(true);
        request<Pack>(`/packs/${currentPack.id}`).then(p => { if (alive)
            setPack(p); }).catch(() => { if (alive)
            setPackError(true); }).finally(() => { if (alive)
            setLoadingPack(false); });
        return () => { alive = false; };
    }, [currentPack?.id, currentPack?.status, currentPack?.revision_id, op?.revision_id]);
    const poll = useCallback(async () => {
        try {
            const runs = await request<Run[]>('/runs');
            setPollError(false);
            const run = runId ? runs.find(r => r.id === runId) : runs.find(r => r.status === 'running' && r.operation_key === `pack:${id}`);
            if (run?.status === 'running') {
                setActive(true);
                setRunId(run.id);
            }
            else if (runId && run) {
                setLastRun(run.id);
                setActive(false);
                setFailed(run.status !== 'completed');
                resource.reload();
                setRunId(undefined);
            }
        }
        catch {
            setPollError(true);
        }
    }, [id, runId, resource.reload]);
    useEffect(() => { void poll(); if (!active)
        return; const timer = window.setInterval(() => { if (!document.hidden)
        void poll(); }, 5000); const visible = () => { if (!document.hidden)
        void poll(); }; document.addEventListener('visibilitychange', visible); return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); }; }, [poll, active]);
    async function build() { const result = await request<{
        run_id: number;
    }>(`/opportunities/${id}/pack`, settings.csrf_token, {}); window.dispatchEvent(new Event('inbound-work-started')); setPack(undefined); setRunId(result.run_id); setActive(true); setFailed(false); }
    if (resource.error)
        return <Failure text="Opportunity could not be loaded." retry={resource.reload}/>;
    if (!op)
        return <Loading text="Loading opportunity…"/>;
    const recommended = op.roles?.find(r => r.id === op.recommended_role_id);
    const latest = op.revisions?.at(-1);
    const revisionNumber = op.revisions?.length || 1;
    const oldReviewed = op.review_history?.some(e => e.action === 'reviewed' && e.revision_id !== op.revision_id);
    return <><Link to={`/${sessionStorage.getItem('inbound-inbox-query') || ''}`} state={{ restore: true }}>Back to Today / Inbox</Link><Section title={fieldValue(op.fields.company?.normalized)}><p className="role-title">{recommended?.title || 'Role unknown'} · Recommended role</p><p>{fieldValue(op.fields.city?.normalized)} · {fieldValue(op.fields.mode?.normalized)} · {fieldValue(op.fields.stipend?.normalized)}</p><p><StatusBadge value={op.kind}/> <StatusBadge value={op.status}/></p><p className="meta">Revision {revisionNumber} · Received {date(latest?.received_at)}</p><DeadlineDisplay record={op.fields.deadline} now={settings.clock} frozen={settings.frozen_clock}/>{oldReviewed && <div className="notice review"><strong>Call updated — review this revision</strong><p>A previous pack was reviewed against an earlier revision. It is no longer current.</p></div>}{op.blocked_reason && <p className="review"><strong>JD unreadable — provisional preview only</strong> · {op.blocked_reason}</p>}<ReviewActions key={`${op.revision_id}-${pack?.id || 'none'}`} opportunity={op} pack={pack} active={active} runId={runId || lastRun} failed={failed || currentPack?.status === 'blocked'} reload={resource.reload} build={build}/>{pollError && <Failure text="Run ledger could not be loaded. Retry." retry={() => void poll()}/>}<ExternalLink title="Open form link" field={op.fields.form_link}/><ExternalLink title="Open application link" field={op.fields.apply_link}/></Section><nav className="jump-links" aria-label="Opportunity sections"><a href="#facts">Facts</a><a href="#roles">Roles</a><a href="#pack">Pack</a><a href="#answers">Answers</a></nav><div className="opportunity-grid"><div><Facts opportunity={op}/><RevisionHistory opportunity={op}/><AttachmentBlocker opportunity={op}/><RoleCoverage opportunity={op}/></div><div>{loadingPack ? <Loading text="Loading pack…"/> : packError ? <Failure text="PDF preview could not be loaded." retry={resource.reload}/> : pack ? <><PackPreview pack={pack} role={recommended?.title || 'Unknown'} revision={revisionNumber}/><p>Output filename: {pack.filename} · {op.fields.cv_naming_rule?.status === 'unknown' ? 'Default approved naming template' : 'Call naming rule'}</p><ProjectSelection pack={pack}/><VerificationList pack={pack}/><FormAnswers pack={pack}/></> : <Section title="PDF preview" id="pack"><p>No pack built for this revision.</p></Section>}</div></div><Section title="Review history">{op.review_history?.length ? op.review_history.map(e => <div key={e.id}><StatusBadge value={e.action}/><p>{date(e.created_at)} · Revision {e.revision_id} · {e.pack_id}</p>{Object.entries(e.details).map(([key, value]) => <p className="meta" key={key}>{key.replaceAll('_', ' ')}: {String(value)}</p>)}</div>) : <p>No review events recorded.</p>}</Section></>;
}
