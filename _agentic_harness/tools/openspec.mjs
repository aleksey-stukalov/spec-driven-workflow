#!/usr/bin/env node

// Invoke the repository's pinned OpenSpec without changing its working directory.
// Project routing belongs to the caller; all CLI arguments pass through unchanged.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const harnessRoot = fileURLToPath(new URL('../', import.meta.url));
const packageRoot = path.join(harnessRoot, 'node_modules', '@fission-ai', 'openspec');

function fail(message) {
  process.stderr.write(`OpenSpec: ${message}\n`);
  process.exit(1);
}

let expectedVersion;
let installedPackage;
try {
  const toolchain = JSON.parse(readFileSync(path.join(harnessRoot, 'package.json'), 'utf8'));
  expectedVersion = toolchain.dependencies['@fission-ai/openspec'];
  installedPackage = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
} catch (error) {
  if (error.code === 'ENOENT') {
    fail(`Pinned toolchain is missing. Run npm ci --prefix ${JSON.stringify(harnessRoot)}.`);
  }
  fail(`Cannot read the pinned toolchain: ${error.message}`);
}

if (!/^\d+\.\d+\.\d+$/.test(expectedVersion)) {
  fail('The toolchain must declare an exact @fission-ai/openspec version.');
}
if (installedPackage.version !== expectedVersion) {
  fail(`Expected version ${expectedVersion}, found ${installedPackage.version}. Run npm ci --prefix ${JSON.stringify(harnessRoot)}.`);
}

const result = spawnSync(process.execPath, [path.join(packageRoot, 'bin', 'openspec.js'), ...process.argv.slice(2)], {
  cwd: process.cwd(),
  env: process.env,
  stdio: 'inherit',
});

if (result.error) {
  fail(`Could not start the CLI: ${result.error.message}`);
}
if (result.signal) {
  process.kill(process.pid, result.signal);
} else {
  process.exit(result.status ?? 1);
}
