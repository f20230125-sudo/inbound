import { useEffect, useMemo, useReducer } from 'react';

// The browser's wall-clock date may differ from the server. Only its elapsed time matters.
export function useServerClock(serverTime: string, frozen: boolean) {
    const anchor = useMemo(() => ({ server: new Date(serverTime).getTime(), received: Date.now() }), [serverTime, frozen]);
    const [, tick] = useReducer((n: number) => n + 1, 0);
    useEffect(() => {
        if (frozen) return;
        const visible = () => { if (!document.hidden) tick(); };
        const timer = window.setInterval(tick, 60000);
        document.addEventListener('visibilitychange', visible);
        return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
    }, [frozen]);
    return frozen || !Number.isFinite(anchor.server) ? serverTime : new Date(anchor.server + Date.now() - anchor.received).toISOString();
}
