import { readFile, unlink } from 'node:fs/promises';
import path from 'node:path';
import { existsSync } from 'node:fs';
/** Stop only the recorded synthetic fixture process before Windows tree cleanup. */
export default async function teardown() {
    const port = process.env.INBOUND_E2E_PORT || '5081';
    let repo = import.meta.dirname;
    while (!existsSync(path.join(repo, 'CODEX_BRIEF.md'))) {
        const parent = path.dirname(repo);
        if (parent === repo)
            throw new Error('Inbound workspace not found');
        repo = parent;
    }
    const file = path.join(repo, `.local/inbound-e2e-${port}.pid`);
    let pid: number;
    try {
        pid = Number(await readFile(file, 'ascii'));
    }
    catch {
        return;
    }
    if (!Number.isSafeInteger(pid) || pid <= 0)
        throw new Error('Invalid Inbound fixture PID');
    try {
        process.kill(pid);
    }
    catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ESRCH')
            throw error;
    }
    await unlink(file);
    await new Promise(resolve => setTimeout(resolve, 500));
}
