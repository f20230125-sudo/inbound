import { expect } from '@playwright/test';
import { audit, identities, test, theme } from './helpers.js';

test('Settings shows the read-only Gmail section, disconnected, with connect instructions', async ({ page }, info) => {
    await theme(page, info.project.name.endsWith('-dark'));
    await page.goto('/settings');
    const section = page.locator('#gmail');
    await expect(section.getByRole('heading', { name: 'Gmail (read-only)' })).toBeVisible();
    await expect(section).toContainText('It cannot send, delete, label or change mail.');
    await expect(section).toContainText('Not connected.');
    await expect(section.getByRole('button', { name: 'Check Gmail now' })).toHaveCount(0);
    await audit(page);
});

test('the open desk updates itself when data changes, without a reload', async ({ page }, info) => {
    // One fictional needs_review message per project, so parallel projects never collide.
    const caseId = { 'desktop-light': 'O-H077', 'mobile-light': 'O-H078', 'desktop-dark': 'O-H079', 'mobile-dark': 'O-H080' }[info.project.name]!;
    await theme(page, info.project.name.endsWith('-dark'));
    const ids = await identities(page);
    await page.goto('/?all=1');
    const row = page.locator(`#message-${ids[caseId].id}`);
    await expect(row).toBeVisible();
    await expect(row).not.toContainText('Manual override');
    await expect(page.locator('.live-status')).toContainText('Live', { timeout: 15000 });
    const navigations: string[] = [];
    page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigations.push(frame.url()); });
    const token = (await (await page.request.get('/api/settings')).json()).csrf_token;
    const changed = await page.request.post(`/api/messages/${ids[caseId].id}/category`, { headers: { 'X-CSRF-Token': token }, data: { category: 'personal' } });
    expect(changed.ok()).toBe(true);
    await expect(row).toContainText('Manual override', { timeout: 20000 });
    expect(navigations).toEqual([]);
});
