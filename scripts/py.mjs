#!/usr/bin/env node
// Runs Python from $TELEPORT_PYTHON, $VIRTUAL_ENV or the repo venv (.venv), else python on PATH.
// Usage: node scripts/py.mjs -m pytest   (same on Windows, macOS and Linux)
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const win = process.platform === 'win32';
const inVenv = (dir) => path.join(dir, win ? 'Scripts/python.exe' : 'bin/python');

const candidates = [
  process.env.TELEPORT_PYTHON,
  process.env.VIRTUAL_ENV && inVenv(process.env.VIRTUAL_ENV),
  inVenv(path.join(root, '.venv')),
].filter(Boolean);
const python = candidates.find((p) => existsSync(p)) ?? (win ? 'python' : 'python3');

const child = spawn(python, process.argv.slice(2), { stdio: 'inherit' });
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => child.kill(sig));
child.on('error', (err) => {
  console.error(`could not run ${python}: ${err.message}. Create the venv first (see README).`);
  process.exit(1);
});
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
