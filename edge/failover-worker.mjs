// Route this Worker over habang222.pro/* while the Cloudflare Tunnel remains
// the DNS origin. A same-route fetch(request) goes to that origin, not back to
// this Worker: https://developers.cloudflare.com/workers/configuration/routing/routes/
const PAGES_ORIGIN = 'https://habang2222.github.io/habage222.pro';
const STATIC_FILE = /^\/(?:[a-z0-9-]+\.html|[a-z0-9-]+\.(?:css|js)|favicon\.ico)$/;
const STATIC_IMAGE = /^\/images\/(?:[a-z0-9-]+\/)*[a-z0-9-]+\.(?:png|jpe?g|webp|svg)$/;
const OFFLINE_BANNER = '<div role="status" aria-live="polite" class="hb-fallback-notice">서버가 일시적으로 연결되지 않아 정적 화면을 보여 드립니다. 로그인, 댓글, 다운로드, API 키, 서버 대여 및 원격 접속은 복구 후 이용할 수 있습니다.</div>';
const OFFLINE_STYLE = '<style>.hb-fallback-notice{box-sizing:border-box;padding:12px 18px;background:#053e38;color:#fff;font:600 15px/1.5 system-ui,sans-serif;text-align:center;position:relative;z-index:9999}</style>';

export function isStaticPath(pathname) {
  return pathname === '/' || STATIC_FILE.test(pathname) || STATIC_IMAGE.test(pathname);
}

export function unavailable(pathname) {
  const headers = {
    'Cache-Control': 'no-store',
    'Retry-After': '30',
    'X-Habang-Fallback': 'unavailable',
    'X-Content-Type-Options': 'nosniff',
  };
  if (pathname.startsWith('/api/')) {
    return new Response(JSON.stringify({error: '서버가 일시적으로 연결되지 않습니다. 잠시 후 다시 시도해 주세요.'}), {
      status: 503, headers: {...headers, 'Content-Type': 'application/json; charset=utf-8'},
    });
  }
  return new Response('서버가 일시적으로 연결되지 않습니다. 잠시 후 다시 시도해 주세요.', {
    status: 503, headers: {...headers, 'Content-Type': 'text/plain; charset=utf-8'},
  });
}

async function fromPages(request, pathname, fetcher) {
  if (!['GET', 'HEAD'].includes(request.method) || !isStaticPath(pathname)) return unavailable(pathname);
  const url = new URL(PAGES_ORIGIN + pathname);
  // Do not forward cookies, authorization headers, or visitor information to
  // GitHub. Query strings are omitted to avoid sending access tokens there.
  const fallback = await fetcher(new Request(url, {
    method: request.method,
    redirect: 'manual',
    headers: {'Accept': pathname.endsWith('.html') || pathname === '/' ? 'text/html' : '*/*'},
  }));
  if (!fallback.ok) return unavailable(pathname);
  const headers = new Headers(fallback.headers);
  headers.set('Cache-Control', 'no-store');
  headers.set('X-Habang-Fallback', 'github-pages');
  headers.set('X-Content-Type-Options', 'nosniff');
  headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  headers.set('X-Frame-Options', 'DENY');
  headers.set('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");
  headers.delete('set-cookie');
  headers.delete('content-length');
  if (request.method === 'HEAD' || !(pathname.endsWith('.html') || pathname === '/')) {
    return new Response(request.method === 'HEAD' ? null : fallback.body, {status: fallback.status, headers});
  }
  const html = await fallback.text();
  if (!/<body(?:\s|>)/i.test(html)) return unavailable(pathname);
  const visible = html.includes('hb-fallback-notice') ? html
    : html.replace(/<head(?:\s[^>]*)?>/i, match => match + OFFLINE_STYLE)
      .replace(/<body(?:\s[^>]*)?>/i, match => match + OFFLINE_BANNER);
  headers.set('Content-Type', 'text/html; charset=utf-8');
  return new Response(visible, {status: 200, headers});
}

export default {
  async fetch(request) {
    const pathname = new URL(request.url).pathname;
    try {
      const primary = await fetch(request);
      if (primary.status < 500) return primary;
    } catch (_) {
      // The tunnel can fail as a network error rather than an HTTP response.
    }
    try {
      return await fromPages(request, pathname, fetch);
    } catch (_) {
      return unavailable(pathname);
    }
  },
};
