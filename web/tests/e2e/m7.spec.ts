import { expect } from '@playwright/test';
import { audit, identities, test, theme } from './helpers.js';

test('Today changes deadline group without navigation when the frozen demo clock is advanced', async ({ page }, info) => {
    await theme(page, info.project.name.endsWith('-dark'));
    const token = (await (await page.request.get('/api/settings')).json()).csrf_token;
    const setClock = async (now: string) => {
        expect((await page.request.post('/api/test/clock', { headers: { 'X-CSRF-Token': token }, data: { now } })).ok()).toBe(true);
    };
    const original = (await (await page.request.get('/api/settings')).json()).clock;
    try {
        await setClock('2026-10-28T07:59:00+04:00');
        const summary = await (await page.request.get('/api/today')).json();
        const candidate = summary.deadlines_48h.find((e: { deadline: { normalized: string } }) => new Date(e.deadline.normalized).getTime() === new Date('2026-10-28T08:00:00+04:00').getTime());
        expect(candidate).toBeTruthy();
        await page.goto('/');
        const upcoming = page.locator('[data-slot=card]').filter({ has: page.getByRole('heading', { name: 'Deadlines within 48 hours', exact: true }) });
        const overdue = page.locator('[data-slot=card]').filter({ has: page.getByRole('heading', { name: 'Overdue / blocked', exact: true }) });
        await expect(upcoming.locator(`[data-case="${candidate.provider_id}"]`)).toHaveCount(1);
        await setClock('2026-10-28T08:01:00+04:00');
        await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
        await expect(upcoming.locator(`[data-case="${candidate.provider_id}"]`)).toHaveCount(0);
        await expect(overdue.locator(`[data-case="${candidate.provider_id}"]`)).toHaveCount(1);
        await expect(page).toHaveURL(/\/$/);
        await audit(page);
    } finally { await setClock(original); }
});

test('record and correct an outside application with visible history and a Today follow-up', async ({ page }, info) => {
    await theme(page, info.project.name.endsWith('-dark'));
    const ids = await identities(page);
    await page.goto(`/opportunity/${ids['P-D16'].opportunity_id}`);
    const opener = page.getByRole('button', { name: /^(I applied outside Inbound|Correct outside application)$/ });
    await opener.click();
    await page.getByLabel('Applied at (Dubai time)').fill('2026-10-28T07:00');
    await page.getByLabel('Application note', { exact: true }).fill('Fictional outside application.');
    await page.getByLabel('Follow-up date (local task only)').fill('2026-11-02');
    await page.getByRole('checkbox', { name: 'I applied myself outside Inbound' }).check();
    await page.getByRole('button', { name: 'Record outside application' }).click();
    await expect(page.getByText('Applied (outside Inbound) on 28 Oct 2026, 07:00', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Mark reviewed', exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Correct outside application' }).click();
    await page.getByLabel('Applied at (Dubai time)').fill('2026-10-28T06:45');
    await page.getByLabel('Application note', { exact: true }).fill('Corrected fictional application time.');
    await page.getByRole('checkbox', { name: 'I applied myself outside Inbound' }).check();
    await page.getByRole('button', { name: 'Record outside application' }).click();
    await expect(page.getByText('Applied (outside Inbound) on 28 Oct 2026, 06:45', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('note: Fictional outside application.', { exact: true }).first()).toBeVisible();
    await audit(page);
    await page.getByRole('link', { name: 'Back to Today / Inbox', exact: true }).click();
    const applications = page.locator('[data-slot=card]').filter({ has: page.getByRole('heading', { name: 'Outside applications / follow-ups', exact: true }) });
    await expect(applications).toContainText('Applied (outside Inbound) on 28 Oct 2026, 06:45');
    await expect(applications).toContainText('Follow-up: 02 Nov 2026');
});
