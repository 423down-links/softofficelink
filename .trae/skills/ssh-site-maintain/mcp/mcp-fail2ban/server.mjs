#!/usr/bin/env node
/**
 * mcp-fail2ban — 零依赖 Fail2ban MCP 服务（stdio）
 *
 * 通过 ssh 别名（默认 423down，可用环境变量 F2B_SSH_ALIAS 覆盖）在远端执行
 * fail2ban-client / 日志命令。凭据复用 ~/.ssh/config + 密钥，密码不落盘。
 *
 * 工具：
 *   f2b_status                 — 服务存活 + 监狱列表（fail2ban-client ping / status）
 *   f2b_jail_status <jail>     — 单个监狱详情（当前封禁 IP、失败次数等）
 *   f2b_ban <jail> <ip>        — 手动封禁 IP（写操作）
 *   f2b_unban <ip> [jail]      — 解封 IP（不指定 jail 则全监狱解封，写操作）
 *   f2b_log_tail <lines> [grep]— 尾部日志，可带过滤正则
 *
 * 安全设计：
 *   - jail 名只允许 [A-Za-z0-9_.-]，IP 只允许合法 IPv4/IPv6，杜绝远程命令注入
 *   - 所有命令经 execFile('ssh', [alias, cmd]) 参数数组执行，不经本地 shell
 */
import { execFile } from 'node:child_process';

const SSH_ALIAS = process.env.F2B_SSH_ALIAS || '423down';
const SSH_TIMEOUT_MS = Number(process.env.F2B_SSH_TIMEOUT_MS || 45000);

const JAIL_RE = /^[A-Za-z0-9_.-]{1,64}$/;
const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;
const IPV6_RE = /^[0-9a-fA-F:]{2,45}$/;

function sshRun(cmd, timeoutMs = SSH_TIMEOUT_MS) {
  return new Promise((resolve) => {
    execFile('ssh', [SSH_ALIAS, cmd], { timeout: timeoutMs, maxBuffer: 4 * 1024 * 1024 }, (err, stdout, stderr) => {
      resolve({ code: err ? (err.code ?? 1) : 0, stdout: (stdout || '').trim(), stderr: (stderr || '').trim() });
    });
  });
}

function ok(text) {
  return { content: [{ type: 'text', text }] };
}
function fail(text) {
  return { content: [{ type: 'text', text }], isError: true };
}

const TOOLS = [
  {
    name: 'f2b_status',
    description: `查看远端 fail2ban 服务状态与监狱列表（经 ssh ${SSH_ALIAS}）。只读。`,
    inputSchema: { type: 'object', properties: {}, required: [] },
    handler: async () => {
      const ping = await sshRun('fail2ban-client ping 2>&1');
      const st = await sshRun('fail2ban-client status 2>&1');
      if (ping.code !== 0) return fail(`fail2ban-client ping 失败:\n${ping.stdout || ping.stderr}`);
      return ok(`pong: ${ping.stdout}\n\n${st.stdout || st.stderr}`);
    },
  },
  {
    name: 'f2b_jail_status',
    description: '查看单个 fail2ban 监狱详情（当前封禁 IP 列表、总失败/封禁数）。只读。',
    inputSchema: {
      type: 'object',
      properties: { jail: { type: 'string', description: '监狱名，如 sshd / nginx-423-cc' } },
      required: ['jail'],
    },
    handler: async ({ jail }) => {
      if (!JAIL_RE.test(jail)) return fail(`非法 jail 名: ${jail}`);
      const r = await sshRun(`fail2ban-client status ${jail} 2>&1`);
      return r.code === 0 ? ok(r.stdout) : fail(r.stdout || r.stderr);
    },
  },
  {
    name: 'f2b_ban',
    description: '在指定监狱手动封禁一个 IP（写操作）。例：测试黑洞 IP 用 192.0.2.x。',
    inputSchema: {
      type: 'object',
      properties: {
        jail: { type: 'string' },
        ip: { type: 'string', description: 'IPv4/IPv6 地址' },
      },
      required: ['jail', 'ip'],
    },
    handler: async ({ jail, ip }) => {
      if (!JAIL_RE.test(jail)) return fail(`非法 jail 名: ${jail}`);
      if (!IPV4_RE.test(ip) && !IPV6_RE.test(ip)) return fail(`非法 IP: ${ip}`);
      const r = await sshRun(`fail2ban-client set ${jail} banip ${ip} 2>&1`);
      return r.code === 0 ? ok(`已在 ${jail} 封禁 ${ip}\n${r.stdout}`) : fail(r.stdout || r.stderr);
    },
  },
  {
    name: 'f2b_unban',
    description: '解封 IP（写操作）。不指定 jail 时用 fail2ban-client unban 全监狱解封。',
    inputSchema: {
      type: 'object',
      properties: {
        ip: { type: 'string' },
        jail: { type: 'string', description: '可选，仅在该监狱解封' },
      },
      required: ['ip'],
    },
    handler: async ({ ip, jail }) => {
      if (!IPV4_RE.test(ip) && !IPV6_RE.test(ip)) return fail(`非法 IP: ${ip}`);
      let cmd;
      if (jail) {
        if (!JAIL_RE.test(jail)) return fail(`非法 jail 名: ${jail}`);
        cmd = `fail2ban-client set ${jail} unbanip ${ip} 2>&1`;
      } else {
        cmd = `fail2ban-client unban ${ip} 2>&1`;
      }
      const r = await sshRun(cmd);
      return r.code === 0 ? ok(`已解封 ${ip}${jail ? `（${jail}）` : '（全部监狱）'}\n${r.stdout}`) : fail(r.stdout || r.stderr);
    },
  },
  {
    name: 'f2b_log_tail',
    description: '查看 fail2ban 日志尾部（/var/log/fail2ban.log），可带 grep -E 过滤正则。只读。',
    inputSchema: {
      type: 'object',
      properties: {
        lines: { type: 'number', description: '行数，默认 30，上限 500' },
        grep: { type: 'string', description: '可选 grep -E 正则，如 "Ban|Unban"' },
      },
      required: [],
    },
    handler: async ({ lines = 30, grep }) => {
      const n = Math.min(Math.max(Math.floor(Number(lines) || 30), 1), 500);
      let cmd = `tail -n ${n} /var/log/fail2ban.log`;
      if (grep) {
        const safe = String(grep).replace(/'/g, "'\\''");
        cmd += ` | grep -E -- '${safe}'`;
      }
      const r = await sshRun(cmd);
      return ok(r.stdout || '(空，无匹配行)\n' + (r.stderr || ''));
    },
  },
];

// ---------- MCP stdio 协议（JSON-RPC 2.0，按行分隔） ----------
let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buf += chunk;
  let i;
  while ((i = buf.indexOf('\n')) > -1) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (line) handle(JSON.parse(line)).catch((e) => process.stderr.write(`handler error: ${e.message}\n`));
  }
});
process.stdin.on('end', () => process.exit(0));

async function handle(msg) {
  if (msg.id === undefined) return; // 通知（notifications/initialized 等）忽略
  try {
    if (msg.method === 'initialize') {
      reply(msg.id, {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: { name: 'mcp-fail2ban', version: '1.0.0' },
      });
    } else if (msg.method === 'tools/list') {
      reply(msg.id, {
        tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
      });
    } else if (msg.method === 'tools/call') {
      const { name, arguments: args = {} } = msg.params || {};
      const tool = TOOLS.find((t) => t.name === name);
      if (!tool) return reply(msg.id, { code: -32602, message: `unknown tool: ${name}` }, true);
      const result = await tool.handler(args);
      reply(msg.id, result);
    } else {
      reply(msg.id, { code: -32601, message: `method not found: ${msg.method}` }, true);
    }
  } catch (e) {
    reply(msg.id, { code: -32603, message: e.message }, true);
  }
}

function reply(id, result, isError = false) {
  const msg = { jsonrpc: '2.0', id, result };
  if (isError) {
    delete msg.result;
    msg.error = result;
  }
  process.stdout.write(JSON.stringify(msg) + '\n');
}
