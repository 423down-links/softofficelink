/**
 * NVIDIA 驱动直链中转（Cloudflare Pages Functions）
 *
 * 背景：NVIDIA CDN（Zen/4.3）有防盗链，只放行 Referer 为 nvidia.com/cn 域的请求；
 * 本站直接给出 CDN 直链，浏览器带的是本站 Referer，必然 403。
 * 这里由 Cloudflare 边缘（海外 IP）加官方 Referer 回源，再把流透传给访客，
 * 访客看到的仍是「点开就下载」的直链，无需先进官方确认页。
 *
 * 路由：/dl/{nvidia 主机名}/{原始路径}
 * 例：/dl/cn.download.nvidia.cn/Windows/621.12hf/xxx.hf.exe
 */

const ALLOWED_HOSTS = new Set([
  'cn.download.nvidia.cn',
  'us.download.nvidia.cn',
  'cn.download.nvidia.com',
  'us.download.nvidia.com',
  'international.download.nvidia.com',
]);

// 国内镜像不可用时，退到官方国际站（同路径文件一致）
const FALLBACK_HOST = 'international.download.nvidia.com';

const ALLOWED_EXT = /\.(exe|msi|zip|7z|cab)$/i;

const PASS_HEADERS = [
  'content-type',
  'content-length',
  'content-range',
  'accept-ranges',
  'last-modified',
  'etag',
];

function bad(status, msg) {
  return new Response(msg, { status, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}

export async function onRequest({ request, params }) {
  const seg = Array.isArray(params.path) ? params.path : String(params.path || '').split('/');
  const host = seg[0];
  const filePath = seg.slice(1).join('/');
  if (!host || !filePath) return bad(400, 'bad request');
  if (!ALLOWED_HOSTS.has(host)) return bad(403, 'host not allowed');
  if (!ALLOWED_EXT.test(filePath)) return bad(403, 'file type not allowed');

  const method = request.method === 'HEAD' ? 'HEAD' : 'GET';
  const range = request.headers.get('Range');

  const upstreamHeaders = {
    'Referer': 'https://www.nvidia.com/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
  };
  if (range) upstreamHeaders['Range'] = range;

  const tryHost = async (h) => {
    const url = `https://${h}/${filePath}`;
    try {
      return await fetch(url, { method, headers: upstreamHeaders, redirect: 'follow' });
    } catch {
      return null;
    }
  };

  let up = await tryHost(host);
  if ((!up || up.status >= 400) && host !== FALLBACK_HOST) {
    const alt = await tryHost(FALLBACK_HOST);
    if (alt && alt.status < 400) up = alt;
  }
  if (!up) return bad(502, 'upstream unreachable');

  const out = new Headers();
  for (const k of PASS_HEADERS) {
    const v = up.headers.get(k);
    if (v) out.set(k, v);
  }
  const name = filePath.split('/').pop() || 'download.exe';
  out.set('Content-Disposition', `attachment; filename="${name.replace(/"/g, '')}"`);
  out.set('Cache-Control', 'public, max-age=3600');
  out.set('X-Content-Type-Options', 'nosniff');

  return new Response(method === 'HEAD' ? null : up.body, {
    status: up.status,
    headers: out,
  });
}
