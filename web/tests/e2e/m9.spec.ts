import { expect } from '@playwright/test';
import { audit, test, theme } from './helpers.js';

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
