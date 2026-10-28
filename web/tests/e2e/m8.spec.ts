import { expect } from '@playwright/test';
import path from 'node:path';
import { audit, identities, keyboardActivate, test, theme } from './helpers.js';

test('recover a named missing JD by keyboard with preview, then build a traced normal pack', async ({ page }, info) => {
    await theme(page, info.project.name.endsWith('-dark'));
    const ids = await identities(page);
    const oid = ids[`M8-${info.project.name}`].opportunity_id;
    await page.goto(`/opportunity/${oid}`);
    await expect(page.getByText('Missing bytes · Review blocked')).toBeVisible();
    await keyboardActivate(page, page.getByRole('button', { name: 'Attach the JD file' }));
    await page.getByLabel('JD file for JD.pdf').setInputFiles(path.resolve('../fixtures/export_sample/attachments/jd-P-D15.pdf'));
    await expect(page.getByRole('heading', { name: 'JD file preview' })).toBeVisible();
    await expect(page.getByText('Roles found', { exact: true })).toBeVisible();
    expect((await (await page.request.get(`/api/opportunities/${oid}`)).json()).blocked_reason).toBeTruthy();
    await audit(page);
    await keyboardActivate(page, page.getByRole('button', { name: 'Use this file for JD.pdf' }));
    // The recovered JD names its own role (Data Intern); its requirements replace the subject-only title.
    await expect(page.getByRole('table', { name: 'Data Intern requirement coverage' })).toBeVisible();
    await expect(page.getByText('Parsed', { exact: true })).toBeVisible();
    await keyboardActivate(page, page.getByRole('button', { name: 'Build pack', exact: true }));
    await expect(page.getByText('Passed', { exact: true }).first()).toBeVisible({ timeout: 30000 });
    await expect(page.getByText('Pack preparing', { exact: false })).toHaveCount(0, { timeout: 30000 });
    const op = (await (await page.request.get(`/api/opportunities/${oid}`)).json());
    const pack = (await (await page.request.get(`/api/packs/${op.packs[0].id}`)).json());
    expect(pack.provisional).toBe(0);
    expect(pack.checks.pages).toBe(1);
    expect(pack.checks.passed).toBe(true);
    await expect(page.getByRole('button', { name: 'Mark reviewed', exact: true })).toBeEnabled();
    await audit(page);
});
