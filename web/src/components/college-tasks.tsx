import { useState } from 'react';
import { Link } from 'react-router';
import { useDesk } from '../App';
import type { CollegeTask } from '../types';
import { DATA_CHANGED, request, useResource } from '../lib/api';
import { date, label } from '../lib/format';
import { DeadlineDisplay, Failure, Loading, Section } from './shared';
import { Button } from './ui/button';

function Task({ task: incoming, reload }: { task: CollegeTask; reload: () => void }) {
    const { settings } = useDesk();
    const [saved, setSaved] = useState<CollegeTask>();
    const task = saved && saved.version > incoming.version ? saved : incoming;
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [until, setUntil] = useState('');
    const [canUndo, setCanUndo] = useState(false);
    async function action(action: string) {
        setBusy(true); setError('');
        try {
            const result = await request<CollegeTask>(`/tasks/${task.id}/action`, settings.csrf_token, { action, expected_version: task.version, ...(action === 'snooze' ? { until: `${until}:00+04:00` } : {}) });
            setSaved(result);
            setCanUndo(action !== 'undo'); reload(); window.dispatchEvent(new Event(DATA_CHANGED));
        } catch (e) { setError(e instanceof Error ? e.message : 'Task action failed.'); }
        finally { setBusy(false); }
    }
    const disabled = busy || settings.paused || settings.mode === 'replay';
    return <article id={`task-${task.id}`} className="college-task" tabIndex={-1}>
        <h3>{task.course || 'Course unknown'} · {task.title}</h3>
        <p className="meta">{label(task.state)}</p>
        <DeadlineDisplay record={task.deadline} now={settings.clock} />
        <p className="meta">{label(task.deadline.status)}{task.snoozed_until && ` · Snoozed until ${date(task.snoozed_until)}`}</p>
        <details><summary>Source and revision history</summary><blockquote>{task.source_quote}</blockquote>
            {task.history.map(rev => <div key={rev.id}><Link to={`/work#message-${rev.message_id}`}>Source message · {date(rev.sent_at)}</Link><blockquote>{rev.source_quote}</blockquote></div>)}
        </details>
        <div className="actions">
            <Button variant="outline" disabled={disabled || task.state === 'done'} onClick={() => void action('done')}>Done</Button>
            <Button variant="outline" disabled={disabled || task.state === 'not_mine'} onClick={() => void action('not_mine')}>Not mine</Button>
            <label>Snooze until (Dubai)<input type="datetime-local" value={until} onChange={e => setUntil(e.target.value)} /></label>
            <Button variant="outline" disabled={disabled || !until} onClick={() => void action('snooze')}>Snooze</Button>
            {(canUndo || task.state !== 'open') && <Button variant="outline" disabled={disabled} onClick={() => void action('undo')}>Undo task action</Button>}
        </div>
        {error && <p role="alert">{error}</p>}
    </article>;
}

export function CollegeTasks() {
    const tasks = useResource<{ items: CollegeTask[] }>('/tasks', true);
    return <Section title="Tasks" id="tasks"><p>I found these college tasks in stored mail. You decide when they are done.</p>
        {tasks.error ? <Failure text="College tasks could not be loaded." retry={tasks.reload} /> : !tasks.value ? <Loading text="Loading college tasks…" /> : !tasks.value.items.length ? <p>No college tasks found in stored mail.</p> : tasks.value.items.map(t => <Task key={t.id} task={t} reload={tasks.reload} />)}
    </Section>;
}
