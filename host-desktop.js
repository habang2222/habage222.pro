(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const status = byId('desktop-status');
  const guest = byId('desktop-guest');
  const member = byId('desktop-member');
  const adminPanel = byId('desktop-admin');
  const requestPanel = byId('desktop-request-panel');
  const current = byId('desktop-current');
  const badge = byId('desktop-badge');
  const form = byId('desktop-request-form');
  const feedback = document.createElement('p'); feedback.className = 'notice'; feedback.hidden = true;
  feedback.setAttribute('role', 'status'); feedback.tabIndex = -1; form.after(feedback);
  let submitting = false;
  function requestMessage(text, error = false) {
    feedback.textContent = text; feedback.hidden = false; feedback.classList.toggle('error', error);
    feedback.focus({preventScroll:true}); feedback.scrollIntoView({block:'nearest',behavior:'instant'});
  }
  form.addEventListener('invalid', event => requestMessage(event.target.validationMessage || '필수 항목을 확인해 주세요.',true),true);
  let session = null;
  let epoch = 0;
  const labels = {pending: '관리자 승인 대기', approved: 'Kali 계정 준비 중', ready: '접속 가능', revoked: '접속 해제', failed: '준비 실패'};
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function message(text, error = false) { status.textContent = text; status.classList.toggle('error', error); }
  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', ...options, headers: {
      ...(options.body ? {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken} : {}),
      ...options.headers
    }});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || '요청을 처리하지 못했습니다. 다시 시도해 주세요.');
    return body;
  }
  function tunnel(user, host) {
    return `ssh -o ExitOnForwardFailure=yes -i "내_개인키_경로" -L 127.0.0.1:13389:127.0.0.1:3389 -N ${user}@${host}`;
  }
  function accessDetails(user, host, admin = false) {
    const block = element('div', 'record');
    block.append(element('p', 'muted', admin ? '기존 관리자 SSH 키와 Kali 계정 비밀번호를 사용합니다.' :
      '신청할 때 등록한 공개키에 맞는 개인키와 별도로 정한 Kali 원격 비밀번호를 사용합니다.'));
    block.append(element('strong', '', `Kali 계정: ${user}`));
    block.append(element('p', 'muted', '아래 명령을 Windows PowerShell에서 실행해 둔 채 원격 데스크톱을 여세요.'));
    block.append(element('pre', '', tunnel(user, host)));
    block.append(element('p', 'muted', 'Windows에서 mstsc 실행 → 컴퓨터 127.0.0.1:13389 → Xorg 세션에서 위 Kali 계정으로 로그인'));
    return block;
  }
  function action(label, handler, danger = false) {
    const button = element('button', 'action' + (danger ? ' danger' : ''), label);
    button.type = 'button';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await handler(); } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    });
    return button;
  }
  function renderMember(data) {
    current.replaceChildren();
    const row = data.request;
    badge.textContent = row ? labels[row.status] || row.status : '신청 전';
    requestPanel.hidden = !!(row && ['approved', 'ready'].includes(row.status)) || data.isAdmin;
    form.hidden = row?.status === 'pending';
    if (row?.status === 'pending' && feedback.hidden) {
      feedback.textContent = '접수 완료 — 관리자 승인을 기다리고 있습니다.'; feedback.hidden = false;
    }
    if (data.isAdmin) {
      badge.textContent = '관리자 접속';
      current.append(accessDetails('habang222', data.sshHost, true));
      return;
    }
    if (!row) { current.append(element('p', 'muted', '아직 Kali 호스트 접속을 신청하지 않았습니다.')); return; }
    current.append(element('p', 'muted', labels[row.status] || row.status));
    if (row.status === 'ready') current.append(accessDetails(row.linuxUser, data.sshHost));
    if (row.status === 'failed' && row.lastError) current.append(element('p', 'error', row.lastError));
    if (row.status !== 'revoked') current.append(action('접속 신청 취소 · 권한 해제', async () => {
      if (!window.confirm('Kali 호스트 접속 권한을 해제할까요? 열려 있는 원격 세션도 종료됩니다.')) return;
      await api('/api/host-desktop', {method: 'DELETE', body: '{}'});
      await refresh(session); message('접속 해제를 요청했습니다.');
    }, true));
  }
  async function renderAdmin() {
    const data = await api('/api/admin/host-desktops');
    byId('desktop-capacity').textContent = String(data.capacity);
    const list = byId('desktop-admin-list'); list.replaceChildren();
    if (!data.requests.length) { list.append(element('p', 'empty', '아직 호스트 접속 신청이 없습니다.')); return; }
    for (const row of data.requests) {
      const record = element('article', 'record');
      record.append(element('strong', '', row.name), element('span', 'pill', labels[row.status] || row.status));
      record.append(element('p', 'meta', `${row.email} · 회원 ID ${row.userId} · ${row.verified ? '이메일 인증·가입 완료' : '인증·가입 미완료'}`));
      if (row.lastError) record.append(element('p', 'error', row.lastError));
      const buttons = element('div', 'button-row');
      const review = async decision => {
        await api(`/api/admin/host-desktops/${row.userId}/review`, {method: 'POST', body: JSON.stringify({decision})});
        await refresh(session); message(decision === 'revoke' ? '접속 권한을 해제했습니다.' : 'Kali 계정 준비를 요청했습니다.');
      };
      if (row.status === 'pending') buttons.append(action('이 회원 승인', () => review('approve')));
      if (row.status === 'failed') buttons.append(action('준비 재시도', () => review('retry')));
      if (row.status !== 'revoked') buttons.append(action('접속 해제', () => review('revoke'), true));
      record.append(buttons); list.append(record);
    }
  }
  async function refresh(next) {
    const currentEpoch = ++epoch;
    const previousUserId = session?.user?.id;
    session = next || null;
    if (previousUserId && previousUserId !== session?.user?.id) { form.reset(); feedback.hidden = true; }
    const complete = Boolean(session?.user?.verified && session?.user?.registrationComplete);
    guest.hidden = complete;
    member.hidden = !complete;
    adminPanel.hidden = !complete || !session.user.isAdmin;
    if (!complete) {
      current.replaceChildren(); byId('desktop-admin-list').replaceChildren();
      message(session?.user ? '이메일 인증과 회원가입을 완료해 주세요.' : '로그인 후 이용할 수 있습니다.');
      return;
    }
    try {
      const data = await api('/api/host-desktop');
      if (currentEpoch !== epoch) return;
      renderMember(data);
      if (data.isAdmin) await renderAdmin();
      if (currentEpoch === epoch) message(data.isAdmin ? '서버 관리자 접속과 회원 승인을 관리할 수 있습니다.' : '신청 상태를 확인했습니다.');
    } catch (error) { if (currentEpoch === epoch) message(error.message, true); }
  }
  byId('desktop-login').addEventListener('click', () => window.dispatchEvent(new Event(session?.user ? 'habang:register' : 'habang:login')));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    const button = form.querySelector('button[type=submit]'); button.disabled = true;
    requestMessage('신청을 서버에 저장하는 중입니다…');
    try {
      const values = new FormData(form);
      await api('/api/host-desktop', {method: 'POST', body: JSON.stringify({
        publicKey: values.get('publicKey'), desktopPassword: values.get('desktopPassword')
      })});
      form.reset(); await refresh(session); requestMessage('접수 완료 — 관리자 승인을 기다리고 있습니다.');
    } catch (error) { requestMessage('신청이 저장되지 않았습니다: ' + error.message, true); }
    finally { submitting = false; button.disabled = false; }
  });
  byId('desktop-refresh').addEventListener('click', () => refresh(session));
  window.addEventListener('habang:session', event => refresh(event.detail));
  window.addEventListener('pagehide', () => form.reset());
  if (window.habangSession) refresh(window.habangSession);
  setInterval(() => { if (!document.hidden && session?.user) refresh(session); }, 15000);
})();
