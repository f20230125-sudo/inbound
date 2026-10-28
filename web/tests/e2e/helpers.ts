import AxeBuilder from '@axe-core/playwright';
import { expect, test as base } from '@playwright/test';
import type { Page } from '@playwright/test';
export const test = base.extend<{
    cleanConsole: void;
}>({
    cleanConsole: [async ({ page }, use) => {
            const errors: string[] = [];
            page.on('pageerror', e => errors.push(e.message));
            page.on('console', m => { if (m.type() === 'error')
                errors.push(m.text()); });
            await page.route('**/*', async (route) => {
                if (new URL(route.request().url()).hostname !== '127.0.0.1')
                    throw new Error('Unexpected external request');
                await route.continue();
            });
            await use();
            expect(errors).toEqual([]);
        }, { auto: true }],
});
export async function theme(page: Page, dark: boolean) { await page.addInitScript(value => localStorage.setItem('inbound-theme', value ? 'dark' : 'light'), dark); }
export async function audit(page: Page) {
    await page.waitForLoadState('networkidle');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([]);
}
export async function identities(page: Page): Promise<Record<string, {
    id: number;
    opportunity_id: number | null;
}>> {
    return Object.fromEntries((await (await page.request.get('/api/messages')).json()).map((m: {
        provider_id: string;
        id: number;
        opportunity_id: number | null;
    }) => [m.provider_id, m]));
}
export async function keyboardActivate(page: Page, target: import('@playwright/test').Locator) {
    // Move to an ordinary focusable control, then exercise its native keyboard path.
    await target.focus();
    await expect(target).toBeFocused();
    await page.keyboard.press('Enter');
}
