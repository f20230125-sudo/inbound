import { useEffect, useState } from 'react';
import { request } from '../lib/api';
import { date } from '../lib/format';
import type { Message } from '../types';
import { Failure, Highlight, Loading } from './shared';

/** Source bodies stay local to the expanded reader, outside live summary refreshes. */
export function MessageSource({ message, open, onOpenChange }: {
    message: Message; open: boolean; onOpenChange: (open: boolean) => void;
}) {
    const [source, setSource] = useState<{ id: number; body_text: string }>();
    const [failed, setFailed] = useState(false);
    const [attempt, setAttempt] = useState(0);
    const loaded = source?.id === message.id;
    useEffect(() => {
        if (!open || loaded) return;
        let active = true;
        setFailed(false);
        request<{ id: number; body_text: string }>(`/messages/${message.id}`)
            .then(value => { if (active) setSource(value); })
            .catch(() => { if (active) setFailed(true); });
        return () => { active = false; };
    }, [message.id, open, loaded, attempt]);
    return <details open={open} onToggle={event => onOpenChange(event.currentTarget.open)}>
        <summary>View source</summary>
        <div id={`source-${message.id}`}>
            <p className="meta">{message.provider_id} · sent {date(message.sent_at)} · subject / body</p>
            {open && (failed ? <Failure text="Source could not be loaded." retry={() => setAttempt(value => value + 1)} />
                : !loaded ? <Loading text="Loading source…" />
                    : <Highlight text={`${message.subject}\nFrom: ${message.sender}\n\n${source.body_text}`} quote={message.source_quote} />)}
        </div>
    </details>;
}
