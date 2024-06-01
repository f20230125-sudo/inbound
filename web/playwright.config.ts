import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
import path from 'node:path';
let repo = import.meta.dirname;
while (!existsSync(path.join(repo, 'CODEX_BRIEF.md'))) {
    const parent = path.dirname(repo);
    if (parent === repo)
        throw new Error('Inbound workspace not found');
    repo = parent;
}
const port = process.env.INBOUND_E2E_PORT || '5081';
export default defineConfig({
    testDir: './tests/e2e', outputDir: path.join(repo, '.local/playwright-m14'), timeout: 180000,
    expect: { timeout: 15000 }, fullyParallel: false, workers: 1,
    globalTeardown: './tests/e2e_teardown.ts',
    reporter: [['list'], ['json', { outputFile: path.join(repo, '.local/reports/m14-playwright.json') }]],
    use: { baseURL: `http://127.0.0.1:${port}`, browserName: 'chromium', trace: 'retain-on-failure' },
    projects: (['light', 'dark'] as const).flatMap(colorScheme => [
        { name: `desktop-${colorScheme}`, use: { colorScheme, viewport: { width: 1440, height: 900 } } },
        { name: `mobile-${colorScheme}`, use: { colorScheme, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    ]),
    webServer: {
        command: `"${path.join(repo, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')}" tests/e2e_server.py`,
        url: `http://127.0.0.1:${port}/api/settings`, timeout: 180000, reuseExistingServer: false,
    },
});
