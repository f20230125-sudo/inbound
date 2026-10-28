import { expect } from '@playwright/test';
import { audit, test, theme } from './helpers.js';

test('journal catches up, streams once, preserves the reader, and replays without writes', async ({ page }, info) => {
    await theme(page, info.project.name.endsWith('-dark'));
    await page.goto('/');
    await expect(page.locator('[data-step-id]').last()).toBeVisible();
    const ids = await page.locator('[data-step-id]').evaluateAll(nodes => nodes.map(n => Number(n.getAttribute('data-step-id'))));
    expect(ids.length).toBeLessThanOrEqual(100);
    expect(new Set(ids).size).toBe(ids.length);
    const settings = await (await page.request.get('/api/settings')).json();
    const messages = await (await page.request.get('/api/messages')).json();
    const mid = messages.find((m: { provider_id: string }) => m.provider_id === 'I01')?.id || messages.at(-1).id;
    // Leave the tail behind. Appending must not move the reader or their focused control.
    await page.evaluate(() => window.scrollTo(0, 0));
    const command = page.getByRole('textbox', { name: 'Ask Scout or give a command' });
    await command.focus();
    const scroll = await page.evaluate(() => window.scrollY);
    const response = await page.request.post(`/api/messages/${mid}/category`, {
        headers: { 'X-CSRF-Token': settings.csrf_token }, data: { category: 'needs_review' },
    });
    expect(response.status()).toBe(200);
    await expect(page.getByRole('button', { name: /New activity/ })).toBeVisible();
    expect(await page.evaluate(() => window.scrollY)).toBe(scroll);
    await expect(command).toBeFocused();
    await page.getByRole('button', { name: /New activity/ }).click();
    await expect(page.getByRole('link', { name: "You corrected this message's category to needs review.", exact: true }).last()).toBeVisible();
    const currentIds = await page.locator('[data-step-id]').evaluateAll(nodes => nodes.map(n => n.getAttribute('data-step-id')));
    expect(currentIds.length).toBeLessThanOrEqual(100);
    expect(new Set(currentIds).size).toBe(currentIds.length);
    const before = await (await page.request.get('/api/agent/steps')).json();
    const mutations: string[] = [];
    page.on('request', request => { if (request.method() !== 'GET') mutations.push(request.url()); });
    await page.getByRole('button', { name: 'Replay last check' }).click();
    await expect(page.getByText(/^Recorded check - /)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Return to live activity' })).toBeVisible();
    await audit(page);
    await page.screenshot({ path: info.outputPath('recorded-check.png'), fullPage: true });
    const after = await (await page.request.get('/api/agent/steps')).json();
    expect(after).toEqual(before);
    expect(mutations).toEqual([]);
    await page.getByRole('button', { name: 'Return to live activity' }).click();
    await expect(page.getByRole('link', { name: "You corrected this message's category to needs review.", exact: true }).last()).toBeVisible();
});
