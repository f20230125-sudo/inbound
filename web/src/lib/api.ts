import { useCallback, useEffect, useState } from 'react';
export class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) { super(message); this.status = status; }
}
export async function request<T>(path: string, token?: string, body?: unknown): Promise<T> {
    const response = await fetch(`/api${path}`, { credentials: 'same-origin', headers: { ...(body !== undefined ? { 'Content-Type': 'application/json', 'X-CSRF-Token': token || '' } : {}) }, ...(body !== undefined ? { method: 'POST', body: JSON.stringify(body) } : {}) });
    const data = await response.json();
    if (!response.ok)
        throw new ApiError(data.message || data.error || 'Request failed', response.status);
    return data as T;
}
export function useResource<T>(path: string, retainOnReload = false) {
    const [value, setValue] = useState<T>();
    const [error, setError] = useState(false);
    const [version, setVersion] = useState(0);
    const reload = useCallback(() => setVersion(v => v + 1), []);
    useEffect(() => { let active = true; if (!retainOnReload) setValue(undefined); setError(false); request<T>(path).then(v => { if (active)
        setValue(v); }).catch(() => { if (active)
        setError(true); }); return () => { active = false; }; }, [path, version, retainOnReload]);
    return { value, error, reload };
}
