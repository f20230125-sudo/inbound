import { useState } from 'react';
import type { Pack } from '../types';
import { date } from '../lib/format';
import { CopyAnswer, Section, StatusBadge } from './shared';
export function PackPreview({ pack, role, revision }: {
    pack: Pack;
    role: string;
    revision: number;
}) {
    const [failed, setFailed] = useState(false);
    return <Section title="PDF preview" id="pack"><p className="field-value">{pack.filename}</p><p>{role} · Revision {revision} · {date(pack.created_at)} · {String(pack.checks.pages)} page</p>{!!pack.provisional && <p className="review"><strong>Provisional preview</strong></p>}{failed ? <p role="alert">PDF preview could not be loaded.</p> : <img className="pdf-page" alt={`First page of ${pack.filename}`} src={`/api/packs/${pack.id}/preview`} onError={() => setFailed(true)}/>}<div className="actions"><a href={pack.pdf_url} target="_blank" rel="noreferrer">Open PDF</a><a href={pack.pdf_url} download={pack.filename}>Download PDF</a>{!!pack.provisional && <span>Provisional preview</span>}</div><p className="meta">The selected projects, approved text and checks are available below.</p></Section>;
}
export function ProjectSelection({ pack }: {
    pack: Pack;
}) {
    return <Section title="Selected projects">{pack.selection.projects.map(p => { const project = pack.evidence.projects.find(e => e.id === p.id); return <div key={p.id}><h3>{project?.title || p.id}</h3><p>{p.why.length ? `Selected for ${p.why.map(id => pack.selection.requirements.find(q => q.id === id)?.text || id).join(', ')} requirements.` : 'Approved general evidence; no requirement-specific match recorded.'}</p><p className="meta">Bullets: {p.bullets.join(', ')}</p><details open><summary>View approved evidence</summary>{p.bullets.map(id => { const b = project?.bullets.find(b => b.id === id); return <div key={id}><p>{b?.text_plain}</p><p className="meta">{id} · {b?.source_file}:{b?.source_line} · {b?.source_hash}</p></div>; })}</details></div>; })}</Section>;
}
export function VerificationList({ pack }: {
    pack: Pack;
}) {
    const checks = pack.checks;
    const rows: [
        string,
        boolean | undefined,
        string
    ][] = [
        ['One page.', typeof checks.pages === 'number' ? checks.pages === 1 : undefined, `${checks.pages ?? 'Not recorded'} page`],
        ['No overfull output.', typeof checks.overfull === 'number' ? checks.overfull === 0 : undefined, `${checks.overfull ?? 'Not recorded'} overfull`],
        ['Correct approved identity.', checks.identity_line_check as boolean | undefined, 'Approved registry identity'],
        ['Every rendered bullet traces to an approved registry entry.', checks.manifest_check === undefined ? undefined : !!checks.manifest_check && checks.traced_bullets === checks.bullet_count, `${checks.traced_bullets ?? 'Not recorded'} / ${checks.bullet_count ?? 'Not recorded'} traced`],
        ['Every listed skill is approved.', checks.approved_skills as boolean | undefined, 'Approved skills registry'],
        ['Filename matches the call rule or approved default.', checks.filename_check as boolean | undefined, pack.filename],
        ['Approved fixed sections and correct demo identity/metadata where applicable.', checks.metadata_check as boolean | undefined, 'Approved fixed templates and PDF metadata'],
        ['Provisional label and source safety.', checks.canary_check === undefined ? undefined : !!checks.canary_check && !!checks.provisional_label_check, 'PDF label and canary checks'],
    ];
    return <Section title="Verification"><ul className="check-list">{rows.map(([text, passed, detail]) => <li key={text}><strong>{text}</strong><StatusBadge value={passed === undefined ? 'Not run' : passed ? 'Passed' : 'Failed'}/><p className="meta">{detail}</p></li>)}<li><strong>Links listed — Not checked online.</strong><StatusBadge value="Not run"/><details><summary>Listed links</summary>{(checks.links as string[] || []).map(link => <p className="meta" key={link}>{link}</p>)}</details></li></ul></Section>;
}
export function FormAnswers({ pack }: {
    pack: Pack;
}) {
    return <Section title="Form answers" id="answers">{pack.answers.map(a => <div key={a.id}><h3>{pack.evidence.projects.find(p => p.id === a.id)?.title || a.id}</h3>{(['purpose', 'technologies', 'challenge_fix'] as const).map(key => <CopyAnswer key={key} label={{ purpose: 'Purpose', technologies: 'Technologies', challenge_fix: 'Challenge / fix' }[key]} answer={a[key]} needed={a.answer_needed.includes(key)} provenance={`${a.provenance.id} · ${a.provenance.source_file} · ${a.provenance.source_hash}`}/>)}</div>)}</Section>;
}
