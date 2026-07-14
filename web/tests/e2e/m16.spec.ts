import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { expect } from '@playwright/test';
import { audit, keyboardActivate, test, theme } from './helpers.js';

test('source bodies load on keyboard expansion and stay cached across live summary refreshes', async ({ page }, info) => {
    await theme(page, info.project.name.endsWith('-dark'));
    const reads: string[] = [];
    page.on('request', request => { if (/\/api\/messages\/\d+$/.test(request.url())) reads.push(request.url()); });
    await page.goto('/work');
    const mail = page.locator('#inbox [data-case]').first();
    await expect(mail).toBeVisible();
    expect(reads).toEqual([]);
    const summary = mail.locator('summary').filter({ hasText: /^View source$/ });
    await keyboardActivate(page, summary);
    await expect(mail.locator('mark').last()).toBeVisible();
    expect(reads).toHaveLength(1);
    await page.evaluate(() => window.dispatchEvent(new Event('inbound-data-changed')));
    await keyboardActivate(page, summary);
    await keyboardActivate(page, summary);
    await expect(mail.locator('mark').last()).toBeVisible();
    expect(reads).toHaveLength(1);
    await audit(page);
});

test('fictional arrival, narrated publication, decision, visible learning, next arrival and replay', async ({ page }, info) => {
    // A second synthetic service keeps arrival tests independent of frozen fixture counts.
    const port = Number(process.env.INBOUND_E2E_PORT || '5081') + 1;
    const origin = `http://127.0.0.1:${port}`;
    const root = path.resolve(import.meta.dirname, '../../..');
    const folder = (await readFile(path.join(root, `.local/inbound-e2e-${port}-mail.txt`), 'utf8')).trim();
    expect(path.relative(path.join(root, '.local'), folder)).not.toMatch(/^\.\.|^[A-Za-z]:/);
    const key = `release-${info.project.name}`;
    const sender = `${key}@fiction.demo.invalid`;
    const arrive = async (index: number) => writeFile(path.join(folder, `${key}-${index}.txt`),
        `id: ${key}-${index}\nthread_id: ${key}-${index}\ndate: 2026-10-28T05:00:00+00:00\nfrom: ${sender}\nto: sara@fiction.demo.invalid\ncc:\nbcc:\nlabels:\nattachments:\nbody_exported: fictional release check\nsubject: Observatory notes\nbody_complete: true\n---\nFictional observatory bulletin ${index}.\n`, 'utf8');
    await theme(page, info.project.name.endsWith('-dark'));
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(origin);
    await expect(page.getByRole('img', { name: /^Scout:/ })).toBeVisible();
    expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
    const token = (await (await page.request.get(`${origin}/api/settings`)).json()).csrf_token;
    const imports = async () => {
        const response = await page.request.post(`${origin}/api/import`, { headers: { 'X-CSRF-Token': token }, data: {} });
        expect(response.status()).toBe(202);
        const run = (await response.json()).run_id;
        await expect.poll(async () => (await (await page.request.get(`${origin}/api/runs`)).json()).find((r: { id: number }) => r.id === run)?.status).toBe('completed');
        return run;
    };
    await arrive(1);
    const firstRun = await imports();
    const newActivity = page.getByRole('button', { name: /New activity/ });
    const narration = page.getByRole('link', { name: /I classified .* messages/ }).last();
    await expect.poll(async () => await narration.isVisible() || await newActivity.isVisible()).toBe(true);
    if (await newActivity.isVisible()) await newActivity.click();
    await expect(narration).toBeVisible();
    const steps = (await (await page.request.get(`${origin}/api/agent/steps`)).json()).steps;
    expect(steps.some((step: { kind: string; run_id: number; phase: string }) => step.kind === 'snapshot.published' && step.run_id === firstRun && step.phase === 'committed_result')).toBe(true);
    const messages = (await (await page.request.get(`${origin}/api/messages`)).json());
    const first = messages.find((m: { provider_id: string }) => m.provider_id === `${key}-1`);
    expect(first.category).toBe('needs_review');
    await page.goto(`${origin}/work?category=needs_review#message-${first.id}`);
    await page.locator(`#message-${first.id}`).getByRole('combobox', { name: 'Correct category' }).selectOption('research');
    await expect(page.locator(`#message-${first.id}`)).toHaveCount(0);
    const learning = (await (await page.request.get(`${origin}/api/learning`)).json());
    const rule = learning.rules.find((r: { origin_id: string }) => r.origin_id === String(first.id));
    expect(rule.status).toBe('suggested');
    await page.goto(`${origin}/memory#rule-${rule.id}`);
    const card = page.locator(`#rule-${rule.id}`);
    await expect(card).toContainText(sender);
    await keyboardActivate(page, card.getByRole('button', { name: 'Activate rule' }));
    await expect(card).toContainText('Activated for future use');
    await arrive(2);
    await imports();
    await expect.poll(async () => {
        const list = (await (await page.request.get(`${origin}/api/messages`)).json());
        return list.find((m: { provider_id: string }) => m.provider_id === `${key}-2`)?.category;
    }).toBe('research');
    await expect(card).toContainText('2 stored messages match');
    await card.getByText('Recent uses', { exact: true }).click();
    await expect(card.getByRole('link', { name: 'Observatory notes', exact: true })).toBeVisible();
    await audit(page);
    await page.screenshot({ path: info.outputPath('next-arrival-learning.png'), fullPage: true });
    await page.goto(origin);
    await expect(page.getByRole('textbox', { name: 'Ask Scout or give a command' })).toBeVisible();
    await page.keyboard.press('Control+k');
    await expect(page.getByRole('textbox', { name: 'Ask Scout or give a command' })).toBeFocused();
    await page.keyboard.press('Escape');
    // Opening the desk saves today's briefing in the background; let that settle first, so
    // the comparison below measures only what the replay does.
    await expect.poll(async () => (await (await page.request.get(`${origin}/api/briefing`)).json()).needs_refresh,
        { timeout: 20000 }).toBe(false);
    const before = await (await page.request.get(`${origin}/api/version`)).json();
    const mutations: string[] = [];
    page.on('request', request => { if (request.method() !== 'GET') mutations.push(request.url()); });
    await keyboardActivate(page, page.getByRole('button', { name: 'Replay last check' }));
    await expect(page.getByText(/^Recorded check - /)).toBeVisible();
    await expect(page.getByRole('list', { name: 'Recorded activity' })).toContainText('I classified');
    expect(await (await page.request.get(`${origin}/api/version`)).json()).toEqual(before);
    expect(mutations).toEqual([]);
    await audit(page);
    expect(await page.locator('main').innerText()).not.toMatch(/\bM\d+\b|milestone/i);
});
