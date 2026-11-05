import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = fileURLToPath(new URL('../../', import.meta.url));
const backendDir = path.join(repoRoot, 'backend');
const tempDir = mkdtempSync(path.join(tmpdir(), 'agrifi-e2e-'));
const databasePath = path.join(tempDir, 'e2e.sqlite3');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const env = {
  ...process.env,
  AGRIFI_USE_SQLITE: '1',
  AGRIFI_SQLITE_PATH: databasePath,
  DJANGO_DEBUG: 'true',
  DJANGO_ALLOWED_HOSTS: 'localhost,127.0.0.1',
  DJANGO_CORS_ALLOWED_ORIGINS: 'http://localhost:4201',
};

function runManagementCommand(args) {
  const result = spawnSync(python, ['manage.py', ...args], {
    cwd: backendDir,
    env,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Django command failed (${result.status}): ${args.join(' ')}`);
  }
}

let server;
let closing = false;

function cleanUp(exitCode = 0) {
  if (closing) return;
  closing = true;
  process.exitCode = exitCode;
  if (server && server.exitCode === null) {
    server.once('exit', () => rmSync(tempDir, { recursive: true, force: true }));
    server.kill();
    return;
  }
  rmSync(tempDir, { recursive: true, force: true });
}

try {
  runManagementCommand(['migrate', '--noinput']);
  runManagementCommand(['seed_demo']);
  server = spawn(python, ['manage.py', 'runserver', 'localhost:8010', '--noreload'], {
    cwd: backendDir,
    env,
    stdio: 'inherit',
  });
  server.on('error', (error) => {
    process.stderr.write(`${error.stack || error}\n`);
    cleanUp(1);
  });
  server.on('exit', (code) => cleanUp(code || 0));
  process.on('SIGINT', () => cleanUp(0));
  process.on('SIGTERM', () => cleanUp(0));
} catch (error) {
  process.stderr.write(`${error.stack || error}\n`);
  cleanUp(1);
}
