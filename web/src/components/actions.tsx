import { useState } from 'react';
import type { Opportunity, Pack } from '../types';
import { useDesk } from '../App';
import { request } from '../lib/api';
import { statuses } from '../lib/format';
import { Button } from './ui/button';
import { mutationReason } from './shared';
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
    const blocked = mutationReason(settings);
    const current = !!pack && pack.revision_id === opportunity.revision_id;
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
        return Promise.resolve(); return request(`/packs/${pack.id}/status`, settings.csrf_token, { status, expected_pack_id: pack.id, expected_revision_id: opportunity.revision_id, acknowledge_blocker: ack, ...(status === 'submitted_by_me' ? { human_submission: true } : {}) }); }
    function skip(undo = false) { return request(`/opportunities/${opportunity.id}/status`, settings.csrf_token, { status: undo ? 'undo_skip' : 'skipped', ...(!undo ? { reason } : {}) }); }
    const disabled = !!blocked || busy || active;
    return <div className="review-actions"><div className="actions"><Button disabled={disabled || !opportunity.recommended_role_id} onClick={() => void mutate(build)}>{opportunity.blocked_reason ? 'Build provisional preview' : failed ? 'Retry build' : 'Build pack'}</Button><Button variant="outline" disabled={disabled || reviewBlocked || pack?.status === 'reviewed'} onClick={() => void mutate(() => review('reviewed'))}>Mark reviewed</Button><Button variant="outline" disabled={disabled || !current || pack?.status !== 'reviewed' || opportunity.status !== 'reviewed'} onClick={() => setConfirm(v => !v)} aria-expanded={confirm}>Mark submitted by me</Button></div>{blocked && <p>{blocked}</p>}{active && <p role="status">Pack preparing · <a href={`/settings?run=${runId}#runs`}>View run</a></p>}{failed && <div role="alert"><p>Pack build failed. No successful pack was created.</p><a href={`/settings?run=${runId}#runs`}>View run</a></div>}{!opportunity.recommended_role_id && <p>Role unknown — no recommended-role pack can be built.</p>}{conflict && <p className="review">Deadline conflicting — review required. A clarifying source revision is needed.</p>}{!!pack?.provisional && <label className="check-label"><input type="checkbox" checked={!!pack.blocker_acknowledged || ack} disabled={disabled || !!pack.blocker_acknowledged} onChange={e => setAck(e.target.checked)}/>I understand that the JD was not read and this pack may miss requirements.</label>}{confirm && <div className="notice"><p>I submitted this application myself</p><Button disabled={disabled || pack?.status !== 'reviewed'} onClick={() => void mutate(() => review('submitted_by_me'))}>Record submission</Button></div>}<div className="skip-area">{selection?.fit === 'low' && <p className="notice review"><strong>{selection.fit_reason}</strong></p>}<label>Reason for skipping<input value={reason} maxLength={1000} disabled={disabled} onChange={e => setReason(e.target.value)}/></label><Button variant="outline" disabled={disabled || opportunity.status === 'submitted_by_me'} onClick={() => void mutate(() => skip(opportunity.status === 'skipped'))}>{opportunity.status === 'skipped' ? 'Undo skip' : 'Skip'}</Button></div><label>Application status<select value={opportunity.status} disabled={disabled} onChange={e => { if (e.target.value === 'skipped')
        void mutate(() => skip()); if (e.target.value === 'reviewed')
        void mutate(() => review('reviewed')); if (e.target.value === 'submitted_by_me')
        setConfirm(true); }}>{Object.entries(statuses).map(([key, title]) => <option key={key} value={key} disabled={key === opportunity.status ? false : key === 'skipped' ? opportunity.status === 'submitted_by_me' : key === 'reviewed' ? reviewBlocked : key === 'submitted_by_me' ? pack?.status !== 'reviewed' : true}>{title}</option>)}</select></label><p role="status">{success}</p>{error && <p role="alert">{error}</p>}</div>;
}
