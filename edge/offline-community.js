(() => {
  'use strict';
  const header = document.createElement('header');
  header.className = 'hb-site-header';
  const nav = document.createElement('nav');
  nav.className = 'hb-toolbar';
  nav.setAttribute('aria-label', '사이트 메뉴');
  const brand = document.createElement('a'); brand.href = './'; brand.textContent = 'habang222'; brand.className = 'hb-header-brand'; nav.append(brand);
  const menu = document.createElement('dialog'); menu.className = 'hb-menu'; menu.id = 'hb-menu'; menu.setAttribute('aria-label', '전체 메뉴');
  const close = document.createElement('button'); close.type = 'button'; close.className = 'hb-link'; close.textContent = '닫기 ×'; close.addEventListener('click', () => menu.close()); menu.append(close);
  const links = document.createElement('nav'); links.className = 'hb-menu-links';
  for (const [label, href, className] of [
    ['API 키', 'api.html', 'hb-link'],
    ['서버 대여', 'servers.html', 'hb-link'],
    ['Kali 원격', 'host-desktop.html', 'hb-link'],
    ['고객지원', 'support.html', 'hb-link'],
  ]) {
    const a = document.createElement('a');
    a.textContent = label;
    a.href = href;
    a.className = className;
    links.append(a);
  }
  menu.append(links);
  const status = document.createElement('span');
  status.className = 'hb-account';
  status.textContent = '서버 연결 대기 중';
  nav.append(status);
  const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'hb-menu-toggle'; toggle.textContent = '☰'; toggle.setAttribute('aria-label','전체 메뉴 열기'); toggle.setAttribute('aria-controls',menu.id); toggle.setAttribute('aria-expanded','false');
  toggle.addEventListener('click',()=>{menu.showModal();toggle.setAttribute('aria-expanded','true');});
  menu.addEventListener('close',()=>{toggle.setAttribute('aria-expanded','false');toggle.focus();});
  nav.append(toggle);
  header.append(nav);
  document.body.prepend(header);
  document.body.append(menu);
  document.addEventListener('click', event => {
    const a = event.target.closest('a[href]');
    if (!a) return;
    const url = new URL(a.href, location.href);
    if (/^\/(?:downloads|auth|api)\//.test(url.pathname)) event.preventDefault();
  });
})();
