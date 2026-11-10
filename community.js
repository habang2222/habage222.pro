(() => {
  'use strict';
  const header = document.createElement('header');
  header.className = 'hb-site-header';
  const nav = document.createElement('nav');
  nav.className = 'hb-toolbar';
  nav.setAttribute('aria-label', '사이트 메뉴');
  for (const [label, href, className] of [
    ['habang222', './', 'hb-header-brand'],
    ['API 키', 'api.html', 'hb-link'],
    ['서버 대여', 'servers.html', 'hb-link'],
  ]) {
    const a = document.createElement('a');
    a.textContent = label;
    a.href = href;
    a.className = className;
    nav.append(a);
  }
  const status = document.createElement('span');
  status.className = 'hb-account';
  status.textContent = '서버 연결 대기 중';
  nav.append(status);
  header.append(nav);
  document.body.prepend(header);
  document.addEventListener('click', event => {
    const a = event.target.closest('a[href]');
    if (!a) return;
    const url = new URL(a.href, location.href);
    if (/^\/(?:downloads|auth|api)\//.test(url.pathname)) event.preventDefault();
  });
})();
