import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useDesk } from '../App';
import { DATA_CHANGED, request } from '../lib/api';
import { date } from '../lib/format';
import type { DailyDispatch } from '../types';
import { Section } from './shared';
import { Button } from './ui/button';

function Facts({ items }: { items: DailyDispatch['items'] }) {
    return <ul>{items.map((item, index) => <li key={index}><Link to={item.href}>{item.text}</Link>
        {item.evidence?.deadline?.source_text && <details><summary>Deadline source excerpt</summary><blockquote>{item.evidence.deadline.source_text}</blockquote></details>}
    </li>)}</ul>;
}

export function DailyBriefing() {
    const { settings, recordedReplay } = useDesk();
    const [params] = useSearchParams();
    const identity = params.get('briefing');
    const recorded = identity !== null;
    const [value, setValue] = useState<DailyDispatch>();
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        let active = true;
        let loading = false;
        async function load() {
            if (loading || document.hidden) return;
            loading = true;
            try {
                const mayGenerate = !recorded && !recordedReplay && !settings.paused && settings.mode === 'local' && !!settings.csrf_token;
                let result = await request<DailyDispatch>(recorded ? `/briefing/${identity}` : '/briefing');
                if (mayGenerate && result.needs_refresh && active) result = await request<DailyDispatch>('/briefing', settings.csrf_token, {});
                if (active) { setValue(result); setError(''); }
            } catch (e) {
                if (active) setError(e instanceof Error ? e.message : 'Briefing unavailable.');
            } finally { loading = false; }
        }
        void load();
        const update = () => { if (!recorded && !recordedReplay) void load(); };
        const timer = window.setInterval(update, 60000);
        window.addEventListener(DATA_CHANGED, update);
        document.addEventListener('visibilitychange', update);
        return () => { active = false; clearInterval(timer); window.removeEventListener(DATA_CHANGED, update); document.removeEventListener('visibilitychange', update); };
    }, [identity, recorded, recordedReplay, settings.mode, settings.paused, settings.csrf_token, retry]);
    return <Section title="Daily briefing" id="daily-briefing">
        {value ? <><p className="dispatch-kicker">{recorded ? 'Recorded briefing' : value.id ? 'Saved briefing' : 'Stored work preview'} · {date(value.created_at)}</p>
            <p>{value.greeting} {value.freshness}</p>
            {value.items.length ? <><Facts items={value.items.slice(0, 6)} />{value.items.length > 6 && <details><summary>All {value.items.length} briefing facts</summary><Facts items={value.items.slice(6)} /></details>}</> : <p>{value.empty}</p>}
            <div className="actions">{value.id && !recorded && <Link to={`/?briefing=${value.id}`}>Replay briefing</Link>}{recorded && <Link to="/">Return to current briefing</Link>}</div>
        </> : !error && <p>Loading daily briefing…</p>}
        {error && <div role="alert"><p>{error}</p><Button variant="outline" onClick={() => setRetry(v => v + 1)}>Retry briefing</Button></div>}
    </Section>;
}
