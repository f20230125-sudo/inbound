import { useCallback, useEffect, useRef, useState } from 'react';
export class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) { super(message); this.status = status; }
}
export const DATA_CHANGED = 'inbound-data-changed';
export async function request<T>(path: string, token?: string, body?: unknown): Promise<T> {
    const multipart = body instanceof FormData;
    const response = await fetch(`/api${path}`, { credentials: 'same-origin', headers: { ...(body !== undefined ? { ...(!multipart ? { 'Content-Type': 'application/json' } : {}), 'X-CSRF-Token': token || '' } : {}) }, ...(body !== undefined ? { method: 'POST', body: multipart ? body : JSON.stringify(body) } : {}) });
    const data = await response.json();
    if (!response.ok)
        throw new ApiError(data.message || data.error || 'Request failed', response.status);
    return data as T;
}
export function useResource<T>(path: string, retainOnReload = false) {
    const [value, setValue] = useState<T>();
    const [error, setError] = useState(false);
    const [version, setVersion] = useState(0);
    // Live updates refetch in the background: the current view stays on screen meanwhile.
    const silent = useRef(false);
    const reload = useCallback(() => setVersion(v => v + 1), []);
    useEffect(() => {
        const changed = () => { silent.current = true; setVersion(v => v + 1); };
        window.addEventListener(DATA_CHANGED, changed);
        return () => window.removeEventListener(DATA_CHANGED, changed);
    }, []);
    useEffect(() => { let active = true; const background = silent.current; silent.current = false; if (!retainOnReload && !background) setValue(undefined); if (!background) setError(false); request<T>(path).then(v => { if (active) { setValue(v); setError(false); } }).catch(() => { if (active && !background)
        setError(true); }); return () => { active = false; }; }, [path, version, retainOnReload]);
    return { value, error, reload };
}
