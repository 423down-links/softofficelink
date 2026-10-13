#!/usr/bin/env node
/**
 * mcp-e2e-client.mjs — MCP stdio 端到端验证客户端（零依赖）
 *
 * 用法：node mcp-e2e-client.mjs <spec.json> [--timeout 30]
 * spec.json 格式：
 * {
 *   "server": "node",                          // 可执行文件
 *   "args": ["...", "..."],                    // 参数数组
 *   "env": { "KEY": "VAL" },                   // 可选附加环境变量
 *   "calls": [                                  // 依次执行的 tools/call
 *     { "name": "execute-command", "arguments": { "command": "hostname" } }
 *   ],
 *   "expectTools": ["execute-command", "upload"] // 可选：断言这些工具存在
 * }
 *
 * 流程：initialize → notifications/initialized → tools/list（打印+断言）
 *       → 逐个 tools/call（打印结果）→ 退出码 0=全部通过，1=失败
 */
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';

const specPath = process.argv[2];
if (!specPath) {
  console.error('usage: mcp-e2e-client.mjs <spec.json> [--timeout sec]');
  process.exit(2);
}
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const timeoutArgIdx = process.argv.indexOf('--timeout');
const CALL_TIMEOUT_MS = (timeoutArgIdx > -1 ? Number(process.argv[timeoutArgIdx + 1]) : 30) * 1000;

const PASS = '\x1b[32mPASS\x1b[0m';
const FAIL = '\x1b[31mFAIL\x1b[0m';
let nextId = 1;
let failures = 0;

const child = spawn(spec.server, spec.args, {
  env: { ...process.env, ...(spec.env || {}) },
  stdio: ['pipe', 'pipe', 'pipe'],
});

const pending = new Map(); // id -> {resolve, reject, timer}
let buffer = '';

function send(obj) {
  child.stdin.write(JSON.stringify(obj) + '\n');
}

function request(method, params) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`request timeout: ${method}`));
    }, CALL_TIMEOUT_MS);
    pending.set(id, { resolve, reject, timer });
    send({ jsonrpc: '2.0', id, method, params });
  });
}

function notify(method, params) {
  send({ jsonrpc: '2.0', method, params });
}

child.stdout.on('data', (chunk) => {
  buffer += chunk.toString();
  let idx;
  while ((idx = buffer.indexOf('\n')) > -1) {
    const line = buffer.slice(0, idx).trim();
    buffer = buffer.slice(idx + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id !== undefined && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      clearTimeout(p.timer);
      pending.delete(msg.id);
      if (msg.error) p.reject(new Error(JSON.stringify(msg.error)));
      else p.resolve(msg.result);
    }
  }
});

let stderrTail = '';
child.stderr.on('data', (c) => { stderrTail = (stderrTail + c.toString()).slice(-2000); });
child.on('exit', (code) => {
  for (const [, p] of pending) { clearTimeout(p.timer); p.reject(new Error(`server exited (${code})`)); }
});

function fmtResult(result, maxLen = 1500) {
  if (!result) return '(null)';
  const parts = [];
  if (Array.isArray(result.content)) {
    for (const c of result.content) {
      if (c.type === 'text') parts.push(c.text);
      else parts.push(`[${c.type}] ${JSON.stringify(c).slice(0, 300)}`);
    }
  } else parts.push(JSON.stringify(result));
  let s = parts.join('\n');
  if (result.isError) s = '[isError=true] ' + s;
  if (s.length > maxLen) s = s.slice(0, maxLen) + `\n...(truncated, total ${s.length} bytes)`;
  return s;
}

async function main() {
  console.log(`# 启动: ${spec.server} ${spec.args.join(' ')}`);

  // 1. initialize
  const init = await request('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'mcp-e2e-verify', version: '1.0' },
  });
  console.log(`# initialize OK: server=${init.serverInfo?.name} v${init.serverInfo?.version} proto=${init.protocolVersion}`);
  notify('notifications/initialized', {});

  // 2. tools/list
  const tools = await request('tools/list', {});
  const names = (tools.tools || []).map((t) => t.name);
  console.log(`# tools(${names.length}): ${names.join(', ')}`);
  if (spec.expectTools) {
    for (const t of spec.expectTools) {
      const ok = names.includes(t);
      console.log(`  [${ok ? PASS : FAIL}] 工具存在: ${t}`);
      if (!ok) failures++;
    }
  }

  // 3. 逐个 tools/call（支持 {{var}} 变量替换 + extract 正则提取上一步结果）
  const vars = {};
  for (const call of spec.calls || []) {
    let argsStr = JSON.stringify(call.arguments || {});
    argsStr = argsStr.replace(/\{\{(\w+)\}\}/g, (m, k) => (vars[k] !== undefined ? vars[k] : m));
    const callArgs = JSON.parse(argsStr);
    const label = `${call.name} ${JSON.stringify(callArgs).slice(0, 120)}`;
    let result;
    try {
      result = await request('tools/call', { name: call.name, arguments: callArgs });
    } catch (e) {
      const wantErr = !!call.expectError;
      console.log(`  [${wantErr ? PASS : FAIL}] ${label}`);
      console.log(`      error: ${e.message}`);
      if (!wantErr) failures++;
      continue;
    }
    const failed = result && result.isError === true;
    const wantErr = !!call.expectError;
    const ok = wantErr ? failed : !failed;
    console.log(`  [${ok ? PASS : FAIL}] ${label}${wantErr ? '（预期被拦截）' : ''}`);
    console.log(`      ${fmtResult(result).split('\n').join('\n      ')}`);
    if (!ok) failures++;
    if (call.extract) {
      const text = (result?.content || []).map((c) => c.text || '').join('\n');
      for (const [varName, pattern] of Object.entries(call.extract)) {
        const m = text.match(new RegExp(pattern));
        if (m) { vars[varName] = m[1] !== undefined ? m[1] : m[0]; console.log(`      >> 提取 ${varName} = ${vars[varName]}`); }
        else { console.log(`      >> 提取 ${varName} 失败（模式未命中）`); failures++; }
      }
    }
  }

  child.kill('SIGTERM');
  await new Promise((r) => setTimeout(r, 300));
  child.kill('SIGKILL');
  console.log(failures === 0 ? `# 结果: 全部通过` : `# 结果: ${failures} 项失败`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(`# 致命错误: ${e.message}`);
  if (stderrTail) console.error(`# server stderr 尾部:\n${stderrTail}`);
  child.kill('SIGKILL');
  process.exit(1);
});
