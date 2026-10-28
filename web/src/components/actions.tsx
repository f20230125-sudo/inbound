import { useId, useState } from 'react';
import type { LearnedRule, Opportunity, Pack } from '../types';
import { useDesk } from '../App';
import { request } from '../lib/api';
import { date, statuses } from '../lib/format';
import { Button } from './ui/button';
import { Textarea } from './ui/textarea';
import { RuleSuggestion } from './learning';
import { mutationReason } from './shared';
export function OutsideApplicationStatus({ activity }: { activity?: Opportunity['outside_application'] }) {
    if (!activity) return null;
    return <div><p>Applied (outside Inbound) on {date(activity.applied_at)}</p>{activity.follow_up && <p>Follow-up: {date(activity.follow_up)} · Local task only</p>}</div>;
}
function dubaiInput(value: string) { return new Date(new Date(value).getTime() + 4 * 3600000).toISOString().slice(0, 16); }
export function OutsideApplicationActions({ opportunity, reload }: { opportunity: Opportunity; reload: () => void }) {
    const { settings } = useDesk();
    const noteId = useId();
    const [open, setOpen] = useState(false);
    const [declared, setDeclared] = useState(false);
    const [at, setAt] = useState('');
    const [note, setNote] = useState('');
    const [followUp, setFollowUp] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [saved, setSaved] = useState(false);
    const activity = opportunity.outside_application;
    const blocked = mutationReason(settings);
    function expand() {
        setAt(dubaiInput(activity?.applied_at || settings.clock));
        setNote(activity?.note || ''); setFollowUp(activity?.follow_up || '');
        setDeclared(false); setSaved(false); setError(''); setOpen(v => !v);
    }
    async function save() {
        setBusy(true); setError('');
        try {
            await request(`/opportunities/${opportunity.id}/applied`, settings.csrf_token, {
                applied_at: `${at}:00+04:00`, human_submission: declared, note, follow_up: followUp || null,
                expected_revision_id: opportunity.revision_id, expected_content_version: opportunity.content_version ?? 0, expected_activity_id: activity?.id ?? null,
            });
            setOpen(false); setDeclared(false); setSaved(true); reload();
        } catch (e) { setError(e instanceof Error ? e.message : 'Application could not be saved. Retry.'); }
        finally { setBusy(false); }
    }
    return <div className="outside-application"><OutsideApplicationStatus activity={activity}/>
        <Button variant="outline" disabled={!!blocked || busy} aria-expanded={open} onClick={expand}>{activity ? 'Correct outside application' : 'I applied outside Inbound'}</Button>
        {blocked && <p>{blocked}</p>}
        {open && <form className="notice" onSubmit={e => { e.preventDefault(); if (declared) void save(); }}>
            <p>Record an application you submitted yourself. Corrections keep the previous record in history.</p>
            <label>Applied at (Dubai time)<input type="datetime-local" required value={at} disabled={!!blocked || busy} onChange={e => setAt(e.target.value)}/></label>
            <label htmlFor={noteId}>Application note</label><Textarea id={noteId} maxLength={1000} value={note} disabled={!!blocked || busy} onChange={e => setNote(e.target.value)}/>
            <label>Follow-up date (local task only)<input type="date" value={followUp} disabled={!!blocked || busy} onChange={e => setFollowUp(e.target.value)}/></label>
            <label className="check-label"><input type="checkbox" checked={declared} disabled={!!blocked || busy} onChange={e => setDeclared(e.target.checked)}/>I applied myself outside Inbound</label>
            <Button type="submit" disabled={!!blocked || busy || !declared || !at}>Record outside application</Button>
        </form>}
        {saved && <p role="status">Outside application saved.</p>}{error && <p role="alert">{error}</p>}
    </div>;
}
export function ReviewActions({ opportunity, pack, active, runId, failed, reload, build }: {
    opportunity: Opportunity;
    pack?: Pack;
    active: boolean;
    runId?: number;
    failed: boolean;
    reload: () => void;
    build: () => Promise<void>;
}) {
    const { settings } = useDesk();
    const [ack, setAck] = useState(false);
    const [confirm, setConfirm] = useState(false);
    const [reason, setReason] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');
    const [rule, setRule] = useState<LearnedRule>();
    const blocked = mutationReason(settings);
    const current = !!pack && pack.revision_id === opportunity.revision_id && (pack.content_version ?? 0) === (opportunity.content_version ?? 0);
    const conflict = opportunity.fields.deadline?.status === 'conflicting';
    const reviewBlocked = !current || !pack?.checks.passed || conflict || !!pack?.provisional && !pack.blocker_acknowledged && !ack || ['skipped', 'submitted_by_me'].includes(opportunity.status);
    const role = opportunity.roles?.find(r => r.id === opportunity.recommended_role_id);
    const selection = pack?.selection || role?.coverage;
    async function mutate(action: () => Promise<unknown>) {
        setBusy(true);
        setError('');
        setSuccess('');
        try {
            await action();
            setSuccess('Change saved.');
            reload();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Change could not be saved. Retry.');
        }
        finally {
            setBusy(false);
        }
    }
    function review(status: string) { if (!pack)
        return Promise.resolve(); return request(`/packs/${pack.id}/status`, settings.csrf_token, { status, expected_pack_id: pack.id, expected_revision_id: opportunity.revision_id, expected_content_version: opportunity.content_version ?? 0, acknowledge_blocker: ack, ...(status === 'submitted_by_me' ? { human_submission: true } : {}) }); }
    async function skip(undo = false) { const result = await request<{ learning_rule: LearnedRule | null }>(`/opportunities/${opportunity.id}/status`, settings.csrf_token, { status: undo ? 'undo_skip' : 'skipped', ...(!undo ? { reason } : {}) }); setRule(result.learning_rule || undefined); }
    const disabled = !!blocked || busy || active;
    return <div className="review-actions"><div className="actions"><Button disabled={disabled || !opportunity.recommended_role_id} onClick={() => void mutate(build)}>{opportunity.blocked_reason ? 'Build provisional preview' : failed ? 'Retry build' : 'Build pack'}</Button><Button variant="outline" disabled={disabled || reviewBlocked || pack?.status === 'reviewed'} onClick={() => void mutate(() => review('reviewed'))}>Mark reviewed</Button><Button variant="outline" disabled={disabled || !current || pack?.status !== 'reviewed' || opportunity.status !== 'reviewed'} onClick={() => setConfirm(v => !v)} aria-expanded={confirm}>Mark submitted by me</Button></div>{blocked && <p>{blocked}</p>}{active && <p role="status">Pack preparing · <a href={`/settings?run=${runId}#runs`}>View run</a></p>}{failed && <div role="alert"><p>Pack build failed. No successful pack was created.</p><a href={`/settings?run=${runId}#runs`}>View run</a></div>}{!opportunity.recommended_role_id && <p>Role unknown — no recommended-role pack can be built.</p>}{conflict && <p className="review">Deadline conflicting — review required. A clarifying source revision is needed.</p>}{!!pack?.provisional && <label className="check-label"><input type="checkbox" checked={!!pack.blocker_acknowledged || ack} disabled={disabled || !!pack.blocker_acknowledged} onChange={e => setAck(e.target.checked)}/>I understand that the JD was not read and this pack may miss requirements.</label>}{confirm && <div className="notice"><p>I submitted this application myself</p><Button disabled={disabled || pack?.status !== 'reviewed'} onClick={() => void mutate(() => review('submitted_by_me'))}>Record submission</Button></div>}<div className="skip-area">{selection?.fit === 'low' && <p className="notice review"><strong>{selection.fit_reason}</strong></p>}<label>Reason for skipping<input value={reason} maxLength={1000} disabled={disabled} onChange={e => setReason(e.target.value)}/></label><Button variant="outline" disabled={disabled || opportunity.status === 'submitted_by_me'} onClick={() => void mutate(() => skip(opportunity.status === 'skipped'))}>{opportunity.status === 'skipped' ? 'Undo skip' : 'Skip'}</Button></div><label>Application status<select value={opportunity.status} disabled={disabled} onChange={e => { if (e.target.value === 'skipped')
        void mutate(() => skip()); if (e.target.value === 'reviewed')
        void mutate(() => review('reviewed')); if (e.target.value === 'submitted_by_me')
        setConfirm(true); }}>{Object.entries(statuses).map(([key, title]) => <option key={key} value={key} disabled={key === opportunity.status ? false : key === 'skipped' ? opportunity.status === 'submitted_by_me' : key === 'reviewed' ? reviewBlocked : key === 'submitted_by_me' ? pack?.status !== 'reviewed' : true}>{title}</option>)}</select></label>{rule && <RuleSuggestion rule={rule} />}<p role="status">{success}</p>{error && <p role="alert">{error}</p>}</div>;
}
