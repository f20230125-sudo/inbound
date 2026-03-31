import type { Field, Opportunity, Revision, Role } from '../types';
import { cityText, date, fieldValue, label } from '../lib/format';
import { ConflictCandidates, Section, SourceText, StatusBadge } from './shared';
import { AttachmentRecovery } from './attachment-recovery';
const fields: Record<string, string> = { company: 'Company', city: 'City', form_link: 'Form link', apply_link: 'Application link', stipend: 'Stipend', mode: 'Internship mode', deadline: 'Submission deadline', company_website: 'Company website', jd_location: 'JD location', cv_naming_rule: 'CV naming rule', internship_dates: 'Internship dates', roles: 'Roles' };
export function FieldProvenance({ name, field, revisions }: {
    name: string;
    field: Field;
    revisions: Revision[];
}) {
    const title = fields[name] || label(name);
    return <div className="field-block"><div><h3>{title}</h3><StatusBadge value={field.status}/></div><div>{field.status === 'conflicting' ? <ConflictCandidates title={title} candidates={field.candidates} revisions={revisions}/> : <><p className="field-value">{field.status === 'unknown' ? 'Unknown' : name === 'deadline' && typeof field.normalized === 'string' ? date(field.normalized) + (field.normalized.length === 10 ? ' · Time not stated' : ' · Dubai') : name === 'city' ? cityText(field.normalized) : fieldValue(field.normalized)}</p>{field.status === 'unknown' ? <p>{field.missing_reason || 'Not stated'}</p> : <SourceText title={title} quote={field.source_text || ''} provenance={field.provenance} revisions={revisions} fallback={field.source_text}/>}{field.observations && new Set(field.observations.map(o => String(o.value))).size > 1 && <><p>Found · Both observations retained</p>{field.observations.map((o, i) => <div key={i}><strong>{fieldValue(o.value)}</strong><SourceText title={title} quote={o.source_text} provenance={o.provenance} revisions={revisions}/></div>)}</>}{field.anchor && <p className="review">“Tomorrow” resolved from this message’s sent time in Dubai: {date(field.anchor)}.</p>}{field.inherited && <p className="meta">Retained from revision {revisions.findIndex(r => r.id === field.provenance?.revision_id) + 1} · {field.provenance?.message_id}</p>}</>}</div></div>;
}
export function Facts({ opportunity }: {
    opportunity: Opportunity;
}) { return <Section title="Facts and provenance" id="facts"><div className="field-head" aria-hidden="true">Field · Value · Status · Source text</div>{Object.keys(fields).map(name => <FieldProvenance key={name} name={name} field={opportunity.fields[name] || { status: 'unknown', missing_reason: 'Not recorded' }} revisions={opportunity.revisions || []}/>)}</Section>; }
export function RevisionHistory({ opportunity }: {
    opportunity: Opportunity;
}) {
    const revisions = opportunity.revisions || [];
    const stale = opportunity.packs?.filter(p => p.revision_id !== opportunity.revision_id || (p.content_version ?? 0) !== (opportunity.content_version ?? 0)) || [];
    const reviewed = opportunity.review_history?.find(e => e.action === "reviewed" && e.revision_id !== opportunity.revision_id);
    return <Section title="Revision history">{reviewed && <div className="notice review"><strong>Call updated — review this revision</strong><p>A previous pack was reviewed against revision {revisions.findIndex(r => r.id === reviewed.revision_id) + 1}. It is no longer current.</p></div>}<ol>{revisions.map((r, i) => <li key={r.id}><strong>Revision {i + 1} · {r.provider_id}</strong><p>Sent {date(r.sent_at)} · Received {date(r.received_at)}</p><SourceText title="revision" quote={r.fields.deadline?.source_text || r.subject} provenance={{ message_id: r.provider_id, sent_at: r.sent_at, revision_id: r.id, location: r.fields.deadline?.source_text ? 'body' : 'subject' }} revisions={revisions}/></li>)}</ol>{stale.map(p => <p key={p.id}>Previous revision — out of date · <a href={`/api/packs/${p.id}/pdf`} target="_blank" rel="noreferrer">Open PDF</a> · {date(p.created_at)}</p>)}{opportunity.merge_suggestions?.map((s, i) => <p key={i}>Possible related call — not merged · <a href={`/opportunity/${s.candidate_id}`}>Inspect related call</a></p>)}</Section>;
}
function RoleDetail({ role, opportunity, recommended }: {
    role: Role;
    opportunity: Opportunity;
    recommended: boolean;
}) {
    const coverage = role.coverage;
    return <div className="role-detail"><h3>{role.title}{recommended ? ' · Recommended' : ''}</h3>{coverage && <p>{coverage.coverage.supported} requirements have approved evidence · {coverage.gaps.length} gaps</p>}{!role.requirements?.length ? <div className="review"><p>{opportunity.blocked_reason ? "Requirements unavailable — attached JD could not be read." : "Requirements unavailable"}</p><p>Title from subject: {role.title}.</p></div> : <div className="responsive-table"><table><caption>{role.title} requirement coverage</caption><thead><tr>{['Requirement', 'Approved evidence', 'Evidence source', 'Coverage'].map(t => <th key={t} scope="col">{t}</th>)}</tr></thead><tbody>{role.requirements.map(q => {
                const matched = coverage?.projects.filter(p => p.why.includes(q.id)) || [];
                const supported = !!coverage && !coverage.gaps.some(g => g.id === q.id);
                const coverageLabel = supported ? 'Supported' : 'Gap: no approved evidence';
                return <tr key={q.id}><td data-label="Requirement"><strong>{q.text}</strong><SourceText title={q.text} quote={q.source_text || q.text} provenance={q.provenance} revisions={opportunity.revisions}/></td><td data-label="Approved evidence">{matched.length ? matched.map(p => { const project = opportunity.evidence?.projects.find(e => e.id === p.id); return <details key={p.id}><summary>{project?.title} · {p.bullets.join(', ')}</summary>{project?.bullets.filter(b => p.bullets.includes(b.id)).map(b => <div key={b.id}><p>{b.text_plain}</p><p className="meta">{b.id} · {b.source_file}:{b.source_line} · {b.source_hash}</p></div>)}</details>; }) : 'No approved evidence'}</td><td data-label="Evidence source">{matched.length ? 'Demo registry entry and approved bullet' : 'None'}</td><td data-label="Coverage" aria-label={coverageLabel} className={!supported ? 'review' : ''}>{coverageLabel}</td></tr>;
            })}</tbody></table></div>}</div>;
}
export function RoleCoverage({ opportunity }: {
    opportunity: Opportunity;
}) {
    const roles = opportunity.roles || [];
    const recommended = roles.find(r => r.id === opportunity.recommended_role_id);
    return <Section title="Roles and coverage" id="roles"><p className="meta">Recommended reflects a deterministic evidence match; employer preference and eligibility are unknown.</p>{recommended && <RoleDetail role={recommended} opportunity={opportunity} recommended/>}{roles.filter(r => r.id !== recommended?.id).map(r => <details key={r.id}><summary>{r.title}</summary><RoleDetail role={r} opportunity={opportunity} recommended={false}/></details>)}{!roles.length && <p>Role unknown — no recommended-role pack can be built.</p>}</Section>;
}
export function AttachmentBlocker({ opportunity, reload = () => {} }: {
    opportunity: Opportunity;
    reload?: () => void;
}) {
    const broken = opportunity.attachments?.some(a => a.purpose === 'JD' && a.parse_status !== 'parsed');
    return <Section title="Attachments">{broken && <div className="notice review"><strong>JD unreadable — provisional preview only</strong><p>Requirements could not be checked. The preview uses the role title and approved evidence.</p><p>{opportunity.blocked_reason}</p></div>}{opportunity.attachments?.map(a => <div key={a.id}><h3>{a.filename}</h3><p>{a.purpose === 'brochure' ? 'Brochure parsed — no role requirements found' : a.parse_status === 'parsed' ? 'Parsed' : a.parse_status === 'missing' ? 'Missing bytes · Review blocked' : a.parse_status === 'unsupported' ? 'Unsupported format · Review blocked' : 'Unreadable · Review blocked'}</p><p className="meta">{a.provider_id} · revision {a.revision_id}</p>{opportunity.blocked_reason && ['missing', 'unreadable'].includes(a.parse_status) && <AttachmentRecovery opportunity={opportunity} attachment={a} reload={reload}/>}{a.locations.map((location, i) => <p className="meta" key={i}>{Object.entries(location).filter(([k]) => k !== 'source_text').map(([k, v]) => `${label(k)}: ${v}`).join(' · ')}</p>)}</div>)}{opportunity.attachment_recoveries?.map(r => <p className="meta" key={r.id}>Supplied by {r.supplier}: {r.original_filename} | {date(r.recorded_at)} | {r.parse_status} | SHA-256 {r.sha256}{r.reason && ` | ${r.reason}`}</p>)}{!opportunity.attachments?.length && <p>{opportunity.fields.jd_location?.normalized === 'absent' ? 'JD not included' : opportunity.fields.jd_location?.status === 'unknown' ? 'JD presence unknown — incomplete export' : 'JD included inline'}</p>}</Section>;
}
