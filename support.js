(() => {
  'use strict';
  const form = document.getElementById('privacy-request-form');
  if (!form) return;
  const guest = document.getElementById('privacy-request-guest');
  const status = document.getElementById('privacy-request-status');
  const list = document.getElementById('privacy-request-list');
  const labels = {export: '자료 열람·내보내기', delete: '계정·자료 삭제'};
  const states = {pending: '접수됨', acknowledged: '검토 중', completed: '처리 완료', rejected: '처리 불가'};
  let session = {user: null, csrfToken: ''};
  let epoch = 0;
  const date = value => value ? new Intl.DateTimeFormat('ko-KR', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value * 1000)) : '—';
  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', ...options, headers: {
      ...(options.body ? {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken} : {}), ...options.headers
    }});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    return body;
  }
  async function refresh(next = window.habangSession) {
    if (!next) return;
    const current = ++epoch;
    session = next;
    guest.hidden = Boolean(session.user);
    form.hidden = !session.user;
    list.replaceChildren();
    if (!session.user) { status.textContent = '로그인하면 본인 정보 요청을 보낼 수 있습니다.'; return; }
    status.textContent = '요청 내역을 확인하고 있습니다.';
    try {
      const data = await api('/api/privacy-requests');
      if (current !== epoch) return;
      status.textContent = data.requests.length ? '요청의 현재 처리 상태입니다.' : '아직 접수한 요청이 없습니다.';
      for (const row of data.requests) {
        const item = document.createElement('article'); item.className = 'record';
        const title = document.createElement('strong'); title.textContent = labels[row.kind] || '정보 요청';
        const meta = document.createElement('p'); meta.className = 'meta';
        meta.textContent = `${states[row.status] || row.status} · 접수 ${date(row.created_at)}`;
        item.append(title, meta); list.append(item);
      }
    } catch (error) { if (current === epoch) status.textContent = error.message; }
  }
  document.getElementById('privacy-request-login').addEventListener('click', () => window.dispatchEvent(new Event('habang:login')));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const kind = form.elements.kind.value;
    if (kind === 'delete' && !window.confirm('계정 삭제 요청을 접수할까요? 접수만으로 즉시 삭제되지는 않으며 관리자가 확인합니다.')) return;
    const button = form.querySelector('button[type=submit]'); button.disabled = true;
    try {
      await api('/api/privacy-requests', {method: 'POST', body: JSON.stringify({kind, message: form.elements.message.value.trim()})});
      form.reset(); await refresh(); status.textContent = '비공개 요청을 접수했습니다. 아래에서 상태를 확인해 주세요.';
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  window.addEventListener('habang:session', event => refresh(event.detail));
  refresh();
})();
