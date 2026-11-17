// 官方直链 UA 白名单代理（FileZilla Pro 只认自家 UA，浏览器点开 403）
// 用法：/dl/filezilla-pro/3.72.1
const RULES = {
  'filezilla-pro': {
    upstream: 'https://prodownload.filezilla-project.org/pro/FileZilla_Pro_{ver}_win64.zip',
    ua: 'FileZilla',
    filename: 'FileZilla_Pro_{ver}_win64.zip',
    type: 'application/zip',
    verRe: /^\d+(\.\d+){1,3}$/,
  },
};

export async function onRequestGet({ params }) {
  const seg = (Array.isArray(params.path) ? params.path : [params.path || ''])
    .join('/').split('/').filter(Boolean);
  const rule = RULES[seg[0]];
  const ver = seg[1] || '';
  if (!rule || !rule.verRe.test(ver)) {
    return new Response('Not Found', { status: 404 });
  }

  const upstream = rule.upstream.replace('{ver}', ver);
  let r;
  try {
    r = await fetch(upstream, {
      headers: { 'User-Agent': rule.ua },
      cf: { cacheEverything: true, cacheTtl: 86400 },
    });
  } catch (e) {
    return new Response('Upstream error', { status: 502 });
  }
  if (!r.ok) return new Response(`Upstream ${r.status}`, { status: r.status });

  const h = new Headers();
  h.set('Content-Type', rule.type);
  h.set('Content-Disposition', `attachment; filename="${rule.filename.replace('{ver}', ver)}"`);
  const len = r.headers.get('Content-Length');
  if (len) h.set('Content-Length', len);
  h.set('Cache-Control', 'public, max-age=86400');
  return new Response(r.body, { status: 200, headers: h });
}
