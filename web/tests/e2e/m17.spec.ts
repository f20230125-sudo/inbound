import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { expect } from '@playwright/test';
import { audit, keyboardActivate, test, theme } from './helpers.js';

test('college arrival, revision, cited briefing, manual actions and recorded playback', async ({ page }, info) => {
    const port = Number(process.env.INBOUND_E2E_PORT || '5081') + 1;
    const origin = `http://127.0.0.1:${port}`;
    const root = path.resolve(import.meta.dirname, '../../..');
    const folder = (await readFile(path.join(root, `.local/inbound-e2e-${port}-mail.txt`), 'utf8')).trim();
    expect(path.relative(path.join(root, '.local'), folder)).not.toMatch(/^\.\.|^[A-Za-z]:/);
    const fixtures = JSON.parse(await readFile(path.join(root, 'fixtures/college.json'), 'utf8')) as { id: string; thread: string; sender: string; subject: string; body: string; sent: string }[];
    // Unique per run: the e2e mail folder can outlive a run, and a reused id would count as a
    // changed copy of the older message (the original is kept, by design).
    const prefix = `college-${info.project.name}-${Date.now()}`;
    // A distinct fictional course per project: the projects share one server, run in turn,
    // and each must find its own quiz rather than an earlier project's revised copy.
    const course = ({ 'desktop-light': 'CS F301', 'mobile-light': 'CS F302', 'desktop-dark': 'CS F303', 'mobile-dark': 'CS F304' } as Record<string, string>)[info.project.name];
    const arrive = async (revision: boolean) => {
        for (const mail of fixtures.filter(f => (f.id === 'revision') === revision)) {
            await writeFile(path.join(folder, `${prefix}-${mail.id}.txt`),
                `id: ${prefix}-${mail.id}\nthread_id: ${prefix}-${mail.thread}\ndate: ${mail.sent}\nfrom: ${mail.sender}\nto: sara@fiction.demo.invalid\ncc:\nbcc:\nlabels:\nattachments:\nbody_exported: fictional college fixture\nsubject: ${mail.subject.replaceAll('CS F211', course)}\nbody_complete: true\n---\n${mail.body.replaceAll('CS F211', course)}\n`, 'utf8');
        }
    };
    await theme(page, info.project.name.endsWith('-dark'));
    await page.goto(origin);
    const imports = async () => {
        // A fresh token each time: the page's own first settings request can start the
        // session at the same moment as ours, and the later cookie wins.
        const fresh = (await (await page.request.get(`${origin}/api/settings`)).json()).csrf_token;
        const result = await page.request.post(`${origin}/api/import`, { headers: { 'X-CSRF-Token': fresh }, data: {} });
        expect(result.status(), await result.text()).toBe(202);
        // Wait for the background import to finish so it never spills into the next test.
        await expect.poll(async () => (await (await page.request.get(`${origin}/api/runs`)).json() as { status: string }[])
            .some(run => run.status === 'running'), { timeout: 60000 }).toBe(false);
    };
    await arrive(false); await imports();
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Work' }).click();
    const tasks = page.locator('#tasks');
    await expect(tasks.getByRole('heading', { name: 'Tasks', exact: true })).toBeVisible();
    const quiz = tasks.locator('article').filter({ has: page.getByRole('heading', { name: `${course} · Quiz 1`, exact: true }) }).first();
    await expect(quiz.getByText(/28 Oct 2026/).first()).toBeVisible();
    await arrive(true); await imports();
    await expect(quiz.getByText(/29 Oct 2026/).first()).toBeVisible();
    await keyboardActivate(page, quiz.getByRole('button', { name: 'Done', exact: true }));
    await expect(quiz.locator('p.meta').filter({ hasText: /^Done$/ })).toBeVisible();
    await keyboardActivate(page, quiz.getByRole('button', { name: 'Undo task action' }));
    await expect(quiz.locator('p.meta').filter({ hasText: /^Open$/ })).toBeVisible();
    await quiz.getByLabel('Snooze until (Dubai)').fill('2026-10-30T10:00');
    await quiz.getByRole('button', { name: 'Snooze', exact: true }).click();
    await expect(quiz.getByText('Snoozed', { exact: true })).toBeVisible();
    await quiz.getByRole('button', { name: 'Undo task action' }).click();
    await quiz.getByRole('button', { name: 'Not mine', exact: true }).click();
    await expect(quiz.locator('p.meta').filter({ hasText: /^Not mine$/ })).toBeVisible();
    await quiz.getByRole('button', { name: 'Undo task action' }).click();
    await expect(quiz.locator('p.meta').filter({ hasText: /^Open$/ })).toBeVisible();
    await quiz.getByText('Source and revision history').click();
    await expect(quiz.getByText(/rescheduled to 29 October/).first()).toBeVisible();
    await audit(page);
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Desk' }).click();
    const briefing = page.locator('#daily-briefing');
    await expect(briefing.getByText(new RegExp(`I found ${course}`)).first()).toBeVisible();
    const command = page.getByRole('textbox', { name: 'Ask Scout or give a command' });
    await command.fill('what assignments are due');
    await page.getByRole('button', { name: 'Ask Scout', exact: true }).click();
    await page.getByRole('button', { name: /College task · source excerpt · version/ }).first().click();
    await expect(page.getByRole('region', { name: 'Cited evidence' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Cited evidence' }).getByRole('link', { name: 'Open source workspace' })).toHaveAttribute('href', /\/work#task-\d+/);
    await audit(page);
    await page.getByRole('button', { name: 'Close evidence' }).click();
    await command.fill('mark Assignment 2 done');
    await page.getByRole('button', { name: 'Ask Scout', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm command' }).click();
    await expect(page.getByText(/You marked this college task done\./).last()).toBeVisible();
    await page.getByRole('button', { name: 'Undo', exact: true }).click();
    await expect(page.getByText(/You undid your college task action\./).last()).toBeVisible();
    await expect(briefing.getByRole('link', { name: 'Replay briefing' })).toBeVisible();
    await briefing.getByRole('link', { name: 'Replay briefing' }).click();
    await expect(briefing.getByText(/Recorded briefing/)).toBeVisible();
    const mutations: string[] = [];
    page.on('request', r => { if (r.method() !== 'GET') mutations.push(r.url()); });
    await audit(page);
    expect(mutations).toEqual([]);
    await page.screenshot({ path: info.outputPath('college-briefing.png'), fullPage: true });
});
