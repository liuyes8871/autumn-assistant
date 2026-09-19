import { exec as execChild, spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createConnection } from 'node:net';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDirectory, '..');
const host = '127.0.0.1';
const port = 5173;
const url = `http://${host}:${port}/`;

function isPortOpen() {
  return new Promise((resolveResult) => {
    const socket = createConnection({ host, port });
    const finish = (value) => {
      socket.destroy();
      resolveResult(value);
    };

    socket.setTimeout(1000);
    socket.once('connect', () => finish(true));
    socket.once('timeout', () => finish(false));
    socket.once('error', () => finish(false));
  });
}

function wait(milliseconds) {
  return new Promise((resolveResult) => setTimeout(resolveResult, milliseconds));
}

async function waitForPort() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await isPortOpen()) return true;
    await wait(500);
  }
  return false;
}

async function main() {
  if (!(await isPortOpen())) {
    const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
    const command = process.platform === 'win32' ? (process.env.ComSpec || 'cmd.exe') : npmCommand;
    const commandArguments = process.platform === 'win32'
      ? ['/d', '/s', '/c', `${npmCommand} --workspace apps/web run dev -- --host ${host} --port ${port}`]
      : ['--workspace', 'apps/web', 'run', 'dev', '--', '--host', host, '--port', String(port)];
    const server = spawn(
      command,
      commandArguments,
      { cwd: projectRoot, detached: true, stdio: 'ignore', windowsHide: true },
    );
    server.unref();

    if (!(await waitForPort())) {
      console.error('开发服务器没有在预期时间内启动，请在项目目录运行 npm run dev 查看具体错误。');
      process.exitCode = 1;
      return;
    }
  }

  if (process.platform === 'win32') {
    execChild(`start "" "${url}"`);
  } else if (process.platform === 'darwin') {
    execChild(`open "${url}"`);
  } else {
    execChild(`xdg-open "${url}"`);
  }

  console.log(`秋招助手已打开：${url}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
