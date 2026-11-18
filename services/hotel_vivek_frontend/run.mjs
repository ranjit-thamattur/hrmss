// Runs the hrms-core frontend with this folder as the client (tenant) folder.
//   npm run dev    -> http://localhost:5173   (needs `npm install` once in ../hrms-core/frontend)
//   npm run build  -> ../hrms-core/frontend/dist
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const core = path.resolve(here, '../hrms-core/frontend');
const cmd = process.argv[2] === 'build' ? 'build' : 'dev';
const child = spawn('npm', ['run', cmd], { cwd: core, stdio: 'inherit', shell: true, env: { ...process.env, TENANT_FRONTEND_DIR: here } });
child.on('exit', (code) => process.exit(code ?? 1));
