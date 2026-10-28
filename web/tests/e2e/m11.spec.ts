import { expect } from '@playwright/test';
import { audit, keyboardActivate, test, theme } from './helpers.js';

test('Scout dispatch: factual briefing, next decisions, ledger, keyboard and reduced motion', async ({ page }, info) => {
    await theme(page, info.project.name.endsWith('-dark'));
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const before = await (await page.request.get('/api/runs')).json();
    // Prime the saved projection; opening an already current Desk remains read-only.
    const settings = (await (await page.request.get('/api/settings')).json());
    expect((await page.request.post('/api/briefing', { headers: { 'X-CSRF-Token': settings.csrf_token }, data: {} })).ok()).toBe(true);
    const state = await (await page.request.get('/api/agent/state')).json();
    const mutations: string[] = [];
    page.on('request', request => { if (request.method() !== 'GET') mutations.push(request.url()); });
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: 'Desk', exact: true })).toBeVisible();
    await expect(page.getByRole('img', { name: /^Scout:/ })).toBeVisible();
    expect(await page.getByRole('navigation', { name: 'Primary' }).getByRole('link').allTextContents()).toEqual(['Desk', 'Work', 'Memory', 'Settings']);
    for (const clause of state.briefing) await expect(page.getByRole('link', { name: clause.text, exact: true })).toBeVisible();
    expect(await page.locator('#decisions li').count()).toBe(Math.min(3, state.counts.decisions));
    expect(await page.locator('#decisions li a').count()).toBe(Math.min(3, state.counts.decisions));
    await expect(page.getByRole('heading', { name: 'My latest work', exact: true })).toBeVisible();
    await page.keyboard.press('Control+k');
    await expect(page.getByRole('textbox', { name: 'Ask Scout or give a command' })).toBeFocused();
    await expect(page.getByText(/Local, supported requests/)).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Ask Scout or give a command' })).toBeEditable();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('link', { name: 'Open all work', exact: true })).toBeFocused();
    await audit(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath('desk.png'), fullPage: true });
    expect(mutations).toEqual([]);
    expect((await (await page.request.get('/api/runs')).json()).length).toBe(before.length);
    await keyboardActivate(page, page.getByRole('link', { name: 'Open all work', exact: true }));
    await expect(page).toHaveURL(/\/work$/);
    const past = page.locator('#past-deadlines');
    await expect(past).not.toHaveAttribute('open', '');
    await keyboardActivate(page, past.locator('summary'));
    await expect(past.locator('li').first()).toBeVisible();
    await audit(page);
});

test('old URLs redirect while retaining filters, source anchors and run selection', async ({ page }) => {
    for (const [old, destination] of [
        ['/?category=ps_call&all=1#inbox', '/work?category=ps_call&all=1#inbox'],
        ['/today?attention=due', '/work?attention=due'], ['/inbox#message-1', '/work#message-1'],
        ['/applications?status=new', '/work?status=new'], ['/runs?run=1', '/settings?run=1#runs'],
    ]) {
        await page.goto(old);
        await expect(page).toHaveURL(new URL(destination, page.url()).href);
    }
});
