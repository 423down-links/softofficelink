/**
 * soft-detect-cron —— GitHub Actions 外部定时兜底（Cloudflare Worker Cron）
 *
 * 作用：GitHub 自带调度器经常丢点（每天只触发 2~7 次），本 Worker 按时补触发
 *       repo 423down-links/softofficelink 的 detect.yml。
 *
 * 策略（真兜底，不是无脑重复触发）：
 *   1. 每次触发先查 GitHub 最近 15 分钟内是否已有 detect.yml 的运行；
 *   2. 有 → 跳过（GitHub 自己跑过了）；没有 → 调 workflow_dispatch 补上；
 *   3. 用 mode 区分：整点=hourly（快检+资源站），:15/:45=full（全量非资源站）。
 *
 * 定时（UTC）：'5 * * * *' 兜整点；'20,50 * * * *' 兜 15/45 分
 *   —— 放在原始时间点之后 5 分钟，给 GitHub 自己先跑的机会，避免抢跑重复。
 *
 * 需要的绑定：GH_PAT（GitHub token，需 workflow scope）、TRIGGER_KEY（手动测试口令）
 */

const OWNER = '423down-links';
const REPO = 'softofficelink';
const WORKFLOW = 'detect.yml';
const REF = 'main';
const DEDUP_MINUTES = 15;

function gh(env, path, init) {
  const headers = {
    Authorization: `Bearer ${env.GH_PAT}`,
    Accept: 'application/vnd.github+json',
    'User-Agent': 'soft-detect-cron',
    'X-GitHub-Api-Version': '2022-11-28',
  };
  if (init && init.body) headers['Content-Type'] = 'application/json';
  return fetch(`https://api.github.com${path}`, { ...init, headers });
}

async function recentRun(env, minutes) {
  const since = Date.now() - minutes * 60_000;
  const r = await gh(env, `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=20`);
  if (!r.ok) return null;
  const j = await r.json();
  for (const run of j.workflow_runs || []) {
    if (new Date(run.created_at).getTime() >= since) return run;
  }
  return null;
}

async function dispatch(env, mode) {
  return gh(env, `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: 'POST',
    body: JSON.stringify({ ref: REF, inputs: { mode } }),
  });
}

async function handle(env, minuteOfHour) {
  const mode = minuteOfHour < 10 ? 'hourly' : 'full';
  const dup = await recentRun(env, DEDUP_MINUTES);
  if (dup) {
    return { action: 'skip', mode, reason: `recent run ${dup.id} (${dup.created_at})` };
  }
  const res = await dispatch(env, mode);
  return { action: res.ok ? 'dispatched' : 'failed', mode, status: res.status };
}

export default {
  async scheduled(event, env, ctx) {
    const minute = new Date(event.scheduledTime).getUTCMinutes();
    ctx.waitUntil(
      handle(env, minute).then((r) => console.log(JSON.stringify({ cron: event.cron, ...r })))
    );
  },

  // 手动验证入口：GET /?key=<TRIGGER_KEY>&min=5  （key 不对直接 404）
  async fetch(req, env, ctx) {
    const u = new URL(req.url);
    if (!env.TRIGGER_KEY || u.searchParams.get('key') !== env.TRIGGER_KEY) {
      return new Response('not found', { status: 404 });
    }
    const min = Number(u.searchParams.get('min') ?? new Date().getUTCMinutes());
    const result = await handle(env, min);
    return Response.json({ ok: true, minute: min, ...result });
  },
};