import { useId, useRef, useState } from 'react';
import { useDesk } from '../App';
import { ApiError, request } from '../lib/api';
import type { Opportunity, Requirement } from '../types';
import { Button } from './ui/button';
import { mutationReason } from './shared';

interface Preview {
    text: string;
    roles: { title: string; requirements: Requirement[] | null }[];
    content_hash: string;
    expected_revision_id: number;
    expected_content_version: number;
    preview_token: string;
    parse_status: string;
    reason: string;
}

export function AttachmentRecovery({ opportunity, attachment, reload }: {
    opportunity: Opportunity;
    attachment: NonNullable<Opportunity['attachments']>[number];
    reload: () => void;
}) {
    const { settings } = useDesk();
    const inputId = useId();
    const heading = useRef<HTMLHeadingElement>(null);
    const input = useRef<HTMLInputElement>(null);
    const sequence = useRef(0);
    const [open, setOpen] = useState(false);
    const [file, setFile] = useState<File>();
    const [preview, setPreview] = useState<Preview>();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [saved, setSaved] = useState(false);
    const blocked = mutationReason(settings);

    async function select(file?: File) {
        const attempt = ++sequence.current;
        setFile(file); setPreview(undefined); setError(''); setSaved(false);
        if (!file) return;
        if (file.size > 10 * 1024 * 1024) {
            setError('Choose a PDF or DOCX of at most 10 MB.'); return;
        }
        setBusy(true);
        const form = new FormData();
        form.set('attachment_id', String(attachment.id)); form.set('file', file);
        try {
            const result = await request<Preview>(`/opportunities/${opportunity.id}/attachments/preview`, settings.csrf_token, form);
            if (attempt !== sequence.current) return;
            if (result.parse_status !== 'parsed') setError(`The JD could not be read: ${result.reason}. The call remains blocked.`);
            else { setPreview(result); requestAnimationFrame(() => heading.current?.focus()); }
        } catch (e) {
            if (attempt === sequence.current) setError(e instanceof Error ? e.message : 'Preview failed. Choose the file again.');
        } finally { if (attempt === sequence.current) setBusy(false); }
    }

    async function confirm() {
        if (!file || !preview) return;
        setBusy(true); setError('');
        const form = new FormData();
        form.set('attachment_id', String(attachment.id)); form.set('file', file);
        for (const key of ['content_hash', 'expected_revision_id', 'expected_content_version', 'preview_token'] as const)
            form.set(key, String(preview[key]));
        try {
            const result = await request<{ parse_status: string; reason: string }>(`/opportunities/${opportunity.id}/attachments/confirm`, settings.csrf_token, form);
            if (result.parse_status !== 'parsed') setError(`The call remains blocked: ${result.reason}`);
            else setSaved(true);
            setPreview(undefined); setFile(undefined); reload();
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Attachment could not be saved. Retry.');
            if (e instanceof ApiError && e.status === 409) setPreview(undefined);
        } finally { setBusy(false); }
    }

    return <div className="attachment-recovery">
        <Button variant="outline" disabled={!!blocked || busy} aria-expanded={open} aria-controls={`${inputId}-panel`}
            onClick={() => { setOpen(true); requestAnimationFrame(() => input.current?.focus()); }}>Attach the JD file</Button>
        {blocked && <p>{blocked}</p>}
        {open && <div id={`${inputId}-panel`}>
            <label htmlFor={inputId}>JD file for {attachment.filename}</label>
            <input ref={input} id={inputId} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                disabled={!!blocked || busy} aria-describedby={`${inputId}-help`} onChange={e => void select(e.target.files?.[0])}/>
            <p id={`${inputId}-help`} className="meta">PDF or DOCX, up to 10 MB. Preview first, then confirm this call and attachment.</p>
        </div>}
        {busy && <p role="status">{preview ? 'Attaching JD file…' : 'Reading JD file…'}</p>}
        {preview && <section aria-labelledby={`${inputId}-preview`} className="notice">
            <h4 id={`${inputId}-preview`} ref={heading} tabIndex={-1}>JD file preview</h4>
            <p>{file?.name} for {attachment.filename}</p>
            <pre className="jd-preview">{preview.text}</pre>
            <h5>Roles found</h5>
            {preview.roles.length ? preview.roles.map((role, i) => <div key={i}><p><strong>{role.title}</strong></p>
                {role.requirements?.length ? <ul>{role.requirements.map((q, j) => <li key={j}>{q.text}</li>)}</ul> : <p>Requirements unknown.</p>}</div>) : <p>No roles detected. Inspect the extracted text before confirming.</p>}
            <Button disabled={!!blocked || busy} onClick={() => void confirm()}>Use this file for {attachment.filename}</Button>
            <Button variant="outline" disabled={busy} onClick={() => { setPreview(undefined); setFile(undefined); input.current?.focus(); }}>Cancel preview</Button>
        </section>}
        {saved && <p role="status">JD file attached. Requirements and coverage updated. Build a new pack to review it.</p>}
        {error && <p role="alert">{error}</p>}
    </div>;
}
