import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router';
import type { Run, Settings } from './types';
import { request } from './lib/api';
import { date } from './lib/format';
import { useServerClock } from './lib/clock';
import { useLive } from './lib/live';
import { PauseControl, Failure, Loading } from './components/shared';
import { Button } from './components/ui/button';
import TodayPage from './pages/Today';
import OpportunityPage from './pages/Opportunity';
import SettingsPage from './pages/Settings';
import DeskPage from './pages/Desk';
import { ScoutFace } from './components/scout';
interface Desk {
    settings: Settings;
    refresh: () => Promise<void>;
    savePause: (value: boolean) => Promise<void>;
}
const Context = createContext<Desk | null>(null);
export function useDesk() { return useContext(Context)!; }
function LegacyRoute({ to, hash }: { to: string; hash?: string }) {
    const location = useLocation();
    return <Navigate replace to={`${to}${location.search}${location.hash || hash || ''}`} state={location.state} />;
}
function DeskRoute() {
    const location = useLocation();
    return location.search || /^#(inbox|message-|source-)/.test(location.hash) ? <LegacyRoute to="/work" /> : <DeskPage />;
}
export default function App() {
    const [settings, setSettings] = useState<Settings>();
    const clock = useServerClock(settings?.clock || '', settings?.frozen_clock ?? true);
    const [error, setError] = useState(false);
    const [activeWork, setActiveWork] = useState(false);
    const [dark, setDark] = useState(() => localStorage.getItem('inbound-theme') === 'dark');
    const location = useLocation();
    const initialRoute = useRef(true);
    const previousPath = useRef(location.pathname);
    const title = location.pathname.startsWith('/opportunity') ? 'Opportunity / Pack' : location.pathname.startsWith('/settings') ? 'Settings' : location.pathname === '/memory' ? 'Memory' : location.pathname === '/work' ? 'Work' : 'Desk';
    const refresh = useCallback(async () => { try {
        setSettings(await request<Settings>('/settings'));
        setError(false);
    }
    catch {
        setError(true);
    } }, []);
    useEffect(() => { void refresh(); }, [refresh, location.pathname]);
    const live = useLive(refresh, !!settings && settings.mode !== 'replay');
    useEffect(() => {
        const visible = () => { if (!document.hidden) void refresh(); };
        document.addEventListener('visibilitychange', visible);
        return () => document.removeEventListener('visibilitychange', visible);
    }, [refresh]);
    useEffect(() => { document.documentElement.classList.toggle('dark', dark); }, [dark]);
    useEffect(() => {
        const checkRuns = () => { if (!document.hidden)
            void request<Run[]>('/runs').then(runs => setActiveWork(runs.some(r => r.status === 'running'))).catch(() => { }); };
        checkRuns();
        const started = () => setActiveWork(true);
        window.addEventListener('inbound-work-started', started);
        const timer = activeWork ? window.setInterval(checkRuns, 5000) : undefined;
        document.addEventListener('visibilitychange', checkRuns);
        return () => { clearInterval(timer); window.removeEventListener('inbound-work-started', started); document.removeEventListener('visibilitychange', checkRuns); };
    }, [activeWork, location.pathname]);
    useEffect(() => {
        document.title = `${title} · Inbound`;
        if (location.pathname.startsWith('/opportunity/'))
            sessionStorage.setItem('inbound-last-opportunity', location.pathname);
        if (initialRoute.current) { initialRoute.current = false; return; }
        const pathChanged = previousPath.current !== location.pathname;
        previousPath.current = location.pathname;
        // Filter and expansion changes keep focus on the control the reader used.
        if (!pathChanged && !location.hash)
            return;
        const restore = () => {
            if (location.state?.restore) {
                const target = document.getElementById(sessionStorage.getItem('inbound-inbox-focus') || '');
                if (!target)
                    return false;
                window.scrollTo(0, Number(sessionStorage.getItem('inbound-inbox-scroll') || 0));
                target.focus({ preventScroll: true });
            }
            else
                document.getElementById('page-title')?.focus();
            if (location.hash)
                document.getElementById(location.hash.slice(1))?.scrollIntoView();
            return true;
        };
        if (restore())
            return;
        const observer = new MutationObserver(() => { if (restore())
            observer.disconnect(); });
        observer.observe(document.getElementById('main')!, { childList: true, subtree: true });
        const cancel = () => observer.disconnect();
        window.addEventListener('pointerdown', cancel, { once: true });
        window.addEventListener('keydown', cancel, { once: true });
        return () => { observer.disconnect(); window.removeEventListener('pointerdown', cancel); window.removeEventListener('keydown', cancel); };
    }, [location.pathname, location.state, location.hash, title]);
    async function savePause(paused: boolean) { const result = await request<{
        paused: boolean;
    }>('/settings', settings?.csrf_token, { paused }); setSettings(v => v && { ...v, paused: result.paused }); }
    const workLink = `/work${sessionStorage.getItem('inbound-inbox-query') || ''}`;
    return <><a className="skip-link" href="#main">Skip to content</a>
        <header className="app-header"><div><Link to="/" className="brand">Inbound</Link><p>{settings?.mode === 'replay' ? 'Synthetic replay · Read-only' : 'Local'}{settings?.mode !== 'replay' && <span className="live-status"> · {live.status === 'live' ? `Live · updated ${live.checkedAt?.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : live.status === 'reconnecting' ? 'Reconnecting…' : 'Connecting…'}</span>}</p></div>
            <div className="header-actions">{settings && <PauseControl paused={settings.paused} replay={settings.mode === 'replay'} save={savePause} active={activeWork}/>}<Button variant="outline" aria-pressed={dark} onClick={() => { setDark(v => !v); localStorage.setItem('inbound-theme', dark ? 'light' : 'dark'); }}>Dark mode</Button></div>
        </header>
        <div className="desk-shell"><nav aria-label="Primary"><NavLink to="/" end>Desk</NavLink><NavLink to={workLink}>Work</NavLink><NavLink to="/memory">Memory</NavLink><NavLink to="/settings">Settings</NavLink></nav>
            <main id="main" tabIndex={-1}><h1 id="page-title" tabIndex={-1}>{title}</h1><div className="meta clock"><p>Dubai time · UTC+04:00</p>{settings?.frozen_clock && <p>Frozen synthetic clock: {date(settings.clock)} · Dubai</p>}</div><div role="status" className="sr-only">{title}</div>
                {error && !settings && location.pathname === '/' && <section className="scout-presence" aria-label="Scout"><ScoutFace mood="disconnected" /><div><h2>Scout</h2><p role="status">I can't reach the local service.</p></div></section>}
                {error && <Failure text="Settings could not be loaded." retry={() => void refresh()}/>}
                {!settings ? !error && <Loading text="Loading settings…"/> : <Context.Provider value={{ settings: { ...settings, clock }, refresh, savePause }}><Routes>
                    <Route path="/" element={<DeskRoute />}/><Route path="/desk" element={<LegacyRoute to="/" />}/>
                    <Route path="/work" element={<TodayPage />}/>
                    <Route path="/today" element={<LegacyRoute to="/work" />}/><Route path="/inbox" element={<LegacyRoute to="/work" />}/><Route path="/applications" element={<LegacyRoute to="/work" />}/>
                    <Route path="/opportunity" element={<LegacyRoute to="/work" />}/><Route path="/opportunity/:id" element={<OpportunityPage />}/>
                    <Route path="/settings" element={<SettingsPage />}/><Route path="/runs" element={<LegacyRoute to="/settings" hash="#runs" />}/>
                    <Route path="/memory" element={<section className="memory-placeholder"><h2>What Scout knows about you</h2><p>Memory arrives in M13. No memories have been imported or learned in this view.</p></section>}/>
                    <Route path="*" element={<p>Choose a call from <Link to="/work">Work</Link></p>}/>
                </Routes></Context.Provider>}
            </main>
        </div></>;
}
