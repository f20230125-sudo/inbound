export interface Citation {
    entity_type: 'revision' | 'message' | 'memory' | 'rule' | 'step' | 'skill' | 'task';
    entity_id: number | string;
    version: number | string;
    label: string;
    url: string;
    snapshot_at?: string;
}
export interface Command { path: string; ticket: string; label: string }
export interface ScoutReply {
    text: string;
    items: { text: string; citations: Citation[] }[];
    choices: { key: string; label: string }[];
    suggestions: string[];
    snapshot_at?: string;
    command?: Command;
    undo?: Command;
    suggestion?: { id: string; title: string; scope: string };
}
export interface Turn { question: string; reply: ScoutReply }
export const HISTORY_KEY = 'inbound-scout-history-v1';

export function boundedHistory(input: unknown): Turn[] {
    if (!Array.isArray(input)) return [];
    const result: Turn[] = [];
    let size = 2;
    for (const candidate of input.slice(-20).reverse()) {
        if (!candidate || typeof candidate.question !== 'string' || candidate.question.length > 500 ||
            !candidate.reply || typeof candidate.reply.text !== 'string' ||
            !Array.isArray(candidate.reply.items) || !Array.isArray(candidate.reply.choices) ||
            !Array.isArray(candidate.reply.suggestions)) continue;
        const valid = candidate.reply.items.length <= 120 && candidate.reply.items.every((item: Turn['reply']['items'][number]) =>
            item && typeof item.text === 'string' && Array.isArray(item.citations) && item.citations.every(c =>
                c && typeof c.label === 'string' && typeof c.url === 'string' &&
                ['revision', 'message', 'memory', 'rule', 'step', 'skill', 'task'].includes(c.entity_type) &&
                c.url.startsWith('/api/scout/citation?ticket=') && c.url.length <= 64040));
        if (!valid || !candidate.reply.choices.every((c: { key: string; label: string }) => c && typeof c.key === 'string' && typeof c.label === 'string') ||
            !candidate.reply.suggestions.every((s: string) => typeof s === 'string')) continue;
        const turn: Turn = { question: candidate.question, reply: { ...candidate.reply, items: [...candidate.reply.items] } };
        while (JSON.stringify(turn).length > 100000 && turn.reply.items.length) turn.reply.items.pop();
        if (turn.reply.items.length < candidate.reply.items.length) turn.reply.text += ' Some result lines exceed the conversation limit. Refine the question to see more.';
        const length = JSON.stringify(turn).length + 1;
        if (size + length > 200000) continue;
        size += length;
        result.unshift(turn);
    }
    return result;
}

export function readHistory(): Turn[] {
    try { return boundedHistory(JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]')); }
    catch { return []; }
}
