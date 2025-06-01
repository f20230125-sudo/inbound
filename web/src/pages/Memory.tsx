import { useCallback, useEffect, useRef, useState } from 'react';
import { useDesk } from '../App';
import { DATA_CHANGED, request } from '../lib/api';
import { date } from '../lib/format';
import { Failure, Loading, mutationReason } from '../components/shared';
import { LearnedRules } from '../components/learning';
import { SafeMarkdown } from '../components/memory-markdown';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import type { MemoryDocument, MemoryRecord, MemorySnapshot } from '../types';

const groups = [['user', 'About you'], ['feedback', 'Preferences'], ['project', 'Projects'], ['reference', 'References']] as const;
const empty: MemoryDocument = { name: '', description: '', type: 'user', content: '' };
type Editor = { id?: string; document: MemoryDocument; version: number; returnId: string };

export default function MemoryPage() {
    const { settings } = useDesk();
    const [snapshot, setSnapshot] = useState<MemorySnapshot>();
    const [loadError, setLoadError] = useState(false);
    const [actionError, setActionError] = useState('');
    const [message, setMessage] = useState('');
    const [busy, setBusy] = useState(false);
    const [editor, setEditor] = useState<Editor>();
    const [forget, setForget] = useState<{ item: MemoryRecord; version: number }>();
    const requestId = useRef(0);
    const reason = mutationReason(settings);
    const load = useCallback(async () => {
        const id = ++requestId.current;
        try { const result = await request<MemorySnapshot>('/memory'); if (id === requestId.current) {
            setSnapshot(result); setLoadError(false);
            setEditor(current => current?.id && !result.items.some(item => item.id === current.id) ? undefined : current);
            setForget(current => current && !result.items.some(item => item.id === current.item.id) ? undefined : current);
        } }
        catch { if (id === requestId.current) setLoadError(true); }
    }, []);
    useEffect(() => {
        void load();
        const changed = () => { void load(); };
        window.addEventListener(DATA_CHANGED, changed);
        return () => { requestId.current++; window.removeEventListener(DATA_CHANGED, changed); };
    }, [load]);
    useEffect(() => {
        if (editor) document.getElementById('memory-name')?.focus();
        else if (forget) document.getElementById('confirm-forget')?.focus();
    }, [editor?.id, !!editor, !!forget]);

    function closeEditor() {
        const id = editor?.returnId;
        setEditor(undefined);
        if (id) document.getElementById(id)?.focus();
    }
    function closeForget() {
        const id = forget?.item.id;
        setForget(undefined);
        if (id) document.getElementById(`forget-${id}`)?.focus();
    }
    async function change(action: string, item?: MemoryRecord, version = snapshot?.version ?? 0, doc?: MemoryDocument) {
        setBusy(true); setActionError(''); setMessage(''); requestId.current++;
        try {
            const result = await request<MemorySnapshot>('/memory', settings.csrf_token, {
                action, expected_version: version, ...(item ? { memory_id: item.id } : {}), ...(doc ? { document: doc } : {}),
            });
            requestId.current++;
            setSnapshot(result); setLoadError(false);
            if (action === 'add' || action === 'edit') closeEditor();
            if (action === 'forget') { setForget(undefined); document.getElementById('memory-add')?.focus(); }
            setMessage(action === 'forget' ? 'Forgotten. Removed from active retrieval and memory history. The original curated file remains with Claude.' : action === 'disable' ? 'Disabled. Removed from active retrieval.' : action === 'enable' ? 'Enabled for retrieval. Prose stays remembered only. Choose a structured preference below to say what should generalize.' : 'Saved locally. Prose stays remembered only. Choose a structured preference below to say what should generalize.');
        } catch (error) { setActionError(error instanceof Error ? error.message : 'Memory could not be saved.'); }
        finally { setBusy(false); }
    }
    async function refresh() {
        setBusy(true); setActionError(''); setMessage(''); requestId.current++;
        try {
            const result = await request<MemorySnapshot>('/memory/refresh', settings.csrf_token, {});
            requestId.current++; setSnapshot(result); setLoadError(false);
            setMessage(result.error ? '' : result.published ? 'Memory snapshot refreshed.' : 'No memory changes found.');
        } catch (error) { setActionError(error instanceof Error ? error.message : 'Snapshot could not be refreshed.'); }
        finally { setBusy(false); }
    }
    function edit(item?: MemoryRecord) {
        if (!snapshot) return;
        setForget(undefined); setActionError('');
        setEditor({ id: item?.id, version: snapshot.version, returnId: item ? `edit-${item.id}` : 'memory-add',
            document: item ? { ...(item.title ? { title: item.title } : {}), name: item.name, description: item.description, type: item.type, content: item.content } : { ...empty } });
    }
    function field<K extends keyof MemoryDocument>(key: K, value: MemoryDocument[K]) {
        setEditor(old => old && { ...old, document: { ...old.document, [key]: value } });
    }
    return <div className="memory-page">
        <section className="memory-intro" aria-labelledby="memory-title"><h2 id="memory-title">What I know about you</h2>
            <p>These are saved memories I can refer to. Remembered prose has no active behavior rule. Memory never approves a CV claim or a skill.</p>
            <p className="meta">Current message evidence takes precedence over memory. Built-in restrictions always apply. Explicit rules and their effects are shown below.</p>
            <div className="memory-toolbar"><Button id="memory-add" disabled={!!reason || busy || !snapshot} onClick={() => edit()}>Add memory</Button><Button variant="outline" disabled={!!reason || busy} onClick={() => void refresh()}>Refresh snapshot</Button></div>
            {reason && <p>{reason}. Saved memories remain readable.</p>}
            <p className="meta">{snapshot?.version ? `Snapshot ${snapshot.version} · Published ${date(snapshot.published_at)}` : 'No memory snapshot published yet.'} · Local service checks for changes every minute while running.</p>
        </section>
        {loadError && <Failure text="Memory could not be loaded. Saved information may be out of date." retry={() => void load()} />}
        {!snapshot && !loadError && <Loading text="Loading memory…" />}
        {snapshot?.error && <div className="notice review" role="status"><strong>Memory snapshot could not be published.</strong><p>A file is incomplete, malformed, outside its root, or exceeds a limit. I kept the previous valid snapshot. Ask Claude to repair the curated files, then refresh.</p></div>}
        <p role="status">{message}</p>{actionError && <p role="alert">{actionError}</p>}
        {editor && <form className="section memory-editor" aria-label={editor.id ? 'Edit memory' : 'Add memory'} onSubmit={event => {
            event.preventDefault();
            const item = editor.id ? snapshot?.items.find(i => i.id === editor.id) : undefined;
            if (editor.id && !item) { setActionError('Memory changed; cancel and refresh before saving.'); return; }
            void change(editor.id ? 'edit' : 'add', item, editor.version, { ...editor.document, ...(editor.id ? {} : { title: editor.document.name }) });
        }} onKeyDown={event => { if (event.key === 'Escape' && !busy) { event.preventDefault(); closeEditor(); } }}>
            <h2>{editor.id ? 'Edit memory' : 'Add a memory'}</h2>
            <p>Saved locally. Editing a curated memory creates a local override; its original source stays visible when it disagrees.</p>
            <label htmlFor="memory-name">Name</label><Input id="memory-name" value={editor.document.name} required maxLength={200} onChange={e => field('name', e.target.value)} />
            <label htmlFor="memory-description">Description</label><Input id="memory-description" value={editor.document.description} required maxLength={2000} onChange={e => field('description', e.target.value)} />
            <label htmlFor="memory-type">Section</label><select id="memory-type" value={editor.document.type} onChange={e => field('type', e.target.value as MemoryDocument['type'])}>{groups.map(([type, title]) => <option key={type} value={type}>{title}</option>)}</select>
            <label htmlFor="memory-content">Content</label><Textarea id="memory-content" value={editor.document.content} required maxLength={60000} rows={8} onChange={e => field('content', e.target.value)} />
            <div className="memory-toolbar"><Button disabled={!!reason || busy} type="submit">Save memory</Button><Button variant="outline" type="button" disabled={busy} onClick={closeEditor}>Cancel</Button></div>
        </form>}
        {forget && <section className="section" aria-label="Forget memory" onKeyDown={event => { if (event.key === 'Escape' && !busy) closeForget(); }}>
            <h2>Forget {forget.item.name}?</h2>
            <p>Forgetting removes this memory from active retrieval and its stored memory versions. {forget.item.origin === 'imported' ? 'The original curated file remains until Claude updates it. A persistent suppression prevents the next scan from restoring it.' : 'The local memory file will be removed.'}</p>
            <p>Historical chat text and already generated artifacts may remain. Journal entries retain IDs, without memory contents.</p>
            <div className="memory-toolbar"><Button id="confirm-forget" disabled={!!reason || busy} onClick={() => void change('forget', forget.item, forget.version)}>Confirm forget</Button><Button variant="outline" disabled={busy} onClick={closeForget}>Cancel forget</Button></div>
        </section>}
        {snapshot && groups.map(([type, title]) => <section className="section memory-group" key={type} aria-labelledby={`memory-group-${type}`}>
            <h2 id={`memory-group-${type}`}>{title}</h2>
            {snapshot.items.filter(i => i.type === type).length === 0 && <p className="meta">No saved memories in this section.</p>}
            {snapshot.items.filter(i => i.type === type).map(item => <article id={`memory-${item.id}`} key={item.id} className="memory-entry" aria-labelledby={`memory-name-${item.id}`}>
                <h3 id={`memory-name-${item.id}`}>{item.display_title || item.name}</h3><p className="meta">{item.name} · {item.description}</p>
                <p><strong>{item.status === 'disabled' ? 'Disabled · Excluded from retrieval' : 'Remembered · No active behavior rule'}</strong></p>
                <p className="meta">{item.scope}</p><SafeMarkdown text={item.content} />
                <dl className="memory-source"><div><dt>Source</dt><dd>{item.origin === 'imported' ? 'Curated snapshot' : 'Saved locally'} · {item.file}{item.local_file && <> · Edited locally in {item.local_file}</>}</dd></div><div><dt>Last change</dt><dd>{date(item.changed_at)} · Version {item.version}</dd></div></dl>
                {item.conflicts.length > 0 ? <div className="notice review"><strong>Conflict needs review</strong>{item.conflicts.map(c => <p key={c}>{c}</p>)}</div> : <p className="meta">No recorded conflict. Prose has not been fact-checked.</p>}
                {item.source_content && <details><summary>Original curated source</summary><p>{item.source_content.name} · {item.source_content.description}</p><SafeMarkdown text={item.source_content.content} /></details>}
                <div className="memory-toolbar"><Button id={`edit-${item.id}`} variant="outline" aria-label={`Edit ${item.name}`} disabled={!!reason || busy} onClick={() => edit(item)}>Edit</Button><Button variant="outline" aria-label={`${item.status === 'disabled' ? 'Enable' : 'Disable'} ${item.name}`} disabled={!!reason || busy} onClick={() => void change(item.status === 'disabled' ? 'enable' : 'disable', item)}> {item.status === 'disabled' ? 'Enable' : 'Disable'}</Button><Button id={`forget-${item.id}`} variant="outline" aria-label={`Forget ${item.name}`} disabled={!!reason || busy} onClick={() => { setEditor(undefined); setActionError(''); setForget({ item, version: snapshot.version }); }}>Forget</Button></div>
            </article>)}
        </section>)}
        <LearnedRules />
    </div>;
}
