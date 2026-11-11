(() => {
  'use strict';
  const root = document.querySelector('[data-portal]');
  if (!root) return;
  const adminPage = root.dataset.portal === 'admin';
  const keysPage = root.dataset.portal === 'keys';
  const rentalsPage = root.dataset.portal === 'rentals';
  const byId = id => document.getElementById(id);
  const status = byId('portal-status');
  let session = {user: null, csrfToken: ''};
  let epoch = 0;
  let refreshTimer;
  let search = '';
  let programCatalog = [];
  const labels = {pending: '승인 대기', queued: '생성 대기', provisioning: '생성 중', running: '실행 중', stopped: '중지됨', starting: '시작 중', stopping: '중지 중', restarting: '재시작 중', terminating: '종료 중', terminated: '종료됨', cancelled: '신청 취소', expired: '이용 만료', rejected: '신청 거절', failed: '작업 실패'};
  const actionLabels = {start: '시작', stop: '중지', restart: '재시작', terminate: '종료', retry: '다시 생성', cancel: '신청 취소'};
  const terminal = new Set(['terminated', 'cancelled', 'expired', 'rejected']);
  const node = (tag, className, text) => { const n = document.createElement(tag); if (className) n.className = className; if (text !== undefined) n.textContent = text; return n; };
  const date = value => value ? new Intl.DateTimeFormat('ko-KR', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value * 1000)) : '—';
  function message(text, error = false) { status.textContent = text; status.classList.toggle('error', error); }
  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', ...options, headers: {
      ...(options.body ? {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken} : {}), ...options.headers
    }});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || '요청을 처리하지 못했습니다. 새로고침 후 다시 시도해 주세요.');
    return body;
  }
  function action(label, handler, danger = false) {
    const button = node('button', 'action' + (danger ? ' danger' : ''), label); button.type = 'button';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await handler(); } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    });
    return button;
  }
  function clearSecret() {
    if (!byId('key-secret')) return;
    byId('key-secret').textContent = '';
    byId('key-once').hidden = true;
  }
  function renderKeys(rows) {
    const list = byId('key-list'); list.replaceChildren();
    if (!rows.length) list.append(node('p', 'empty', '아직 발급한 API 키가 없습니다.'));
    for (const row of rows) {
      const record = node('article', 'record');
      const expired = row.expires_at * 1000 <= Date.now();
      record.append(node('strong', '', row.name), node('span', 'pill', row.revoked_at ? '폐기됨' : expired ? '만료됨' : '활성'));
      const programId = row.scopes[0]?.replace('download:', '');
      const programName = programCatalog.find(p => p.id === programId)?.name || programId;
      record.append(node('p', 'meta', `${row.prefix} · ${programName}`));
      record.append(node('p', 'meta', `발급 ${date(row.created_at)} · 만료 ${date(row.expires_at)} · 사용 ${row.use_count}회 · 마지막 사용 ${date(row.last_used_at)}`));
      if (!row.revoked_at && !expired) record.append(action('키 폐기', async () => {
        if (!window.confirm(`“${row.name}” 키를 폐기할까요? 이 키를 사용하는 프로그램의 접근이 중단됩니다.`)) return;
        await api(`/api/keys/${row.id}`, {method: 'DELETE', body: '{}'});
        clearSecret(); await loadMember(); message('API 키를 폐기했습니다.');
      }, true));
      list.append(record);
    }
  }
  function rentalRecord(row, forAdmin = false) {
    const record = node('article', 'record');
    record.append(node('strong', '', row.name), node('span', 'pill', labels[row.status] || row.status));
    if (forAdmin) record.append(node('p', 'meta', `신청자 ${row.ownerName} · 회원 ID ${row.user_id}`));
    record.append(node('p', 'meta', `신청 ${date(row.created_at)} · 만료 ${date(row.expires_at)}`));
    if (row.last_error) record.append(node('p', 'error', row.last_error));
    if (row.status === 'pending') record.append(node('p', 'muted', '관리자가 이 신청 또는 계정을 승인하면 자동으로 생성됩니다.'));
    if (row.sshPort) {
      record.append(node('pre', '', `ssh -p ${row.sshPort} ${row.sshUser}@${row.sshHost}`));
      record.append(node('p', 'meta', `Tailscale 연결 필요 · SFTP도 같은 주소·포트·계정과 SSH 개인키로 접속`));
      if (row.sshFingerprint) record.append(node('p', 'meta', `서버 호스트 키 지문: ${row.sshFingerprint}`));
      if (!forAdmin && row.status === 'running') {
        record.append(node('strong', '', '원격 데스크톱'));
        record.append(node('p', 'muted', 'PC에서 아래 SSH 터널 명령을 실행한 채 유지하세요. 기본 키가 아닌 경우 -i "개인키_경로"를 추가합니다.'));
        record.append(node('pre', '', `ssh -o ExitOnForwardFailure=yes -L 127.0.0.1:6080:127.0.0.1:6080 -N -p ${row.sshPort} ${row.sshUser}@${row.sshHost}`));
        const desktop = node('a', 'action', '내 PC에서 데스크톱 열기 ↗');
        desktop.href = 'http://127.0.0.1:6080/vnc.html?autoconnect=1';
        desktop.target = '_blank'; desktop.rel = 'noopener noreferrer';
        record.append(desktop);
      }
    }
    const buttons = node('div', 'button-row');
    if (forAdmin && row.status === 'pending') {
      for (const [decision, label] of [['approve', '이번 신청 승인'], ['reject', '거절']]) buttons.append(action(label, async () => {
        await api(`/api/admin/rentals/${row.id}/review`, {method: 'POST', body: JSON.stringify({decision})});
        await loadAdmin(); message(decision === 'approve' ? '신청을 승인했습니다. 서버를 자동 생성합니다.' : '신청을 거절했습니다.');
      }, decision === 'reject'));
    }
    for (const value of row.actions) buttons.append(action(actionLabels[value], async () => {
      if (['stop', 'restart', 'terminate'].includes(value) && !window.confirm(`워크스페이스를 ${actionLabels[value]}할까요? 임시 작업 파일은 초기화됩니다. 필요한 파일을 먼저 보관해 주세요.`)) return;
      await api(`/api/rentals/${row.id}/actions`, {method: 'POST', body: JSON.stringify({action: value})});
      await (forAdmin ? loadAdmin() : loadMember()); message('요청을 접수했습니다. 처리 상태를 확인해 주세요.');
    }, value === 'terminate'));
    record.append(buttons); return record;
  }
  async function loadMember() {
    const owner = session.user?.id;
    if (!owner) return;
    const [services, keys, rentals] = await Promise.all([api('/api/services'), keysPage ? api('/api/keys') : null, rentalsPage ? api('/api/rentals') : null]);
    if (session.user?.id !== owner) return;
    if (keysPage && !programCatalog.length) {
      programCatalog = services.programs;
      const chosen = new URL(location.href).searchParams.get('download');
      for (const id of ['key-program', 'guide-program']) {
        const select = byId(id); select.replaceChildren();
        for (const item of programCatalog) { const option = node('option', '', item.name); option.value = item.id; select.append(option); }
        if (programCatalog.some(p => p.id === chosen)) select.value = chosen;
      }
      byId('guide-program').addEventListener('change', renderExamples); renderExamples();
      const programs = byId('program-list'); programs.replaceChildren();
      for (const item of programCatalog) {
        const record = node('article', 'record'); record.append(node('strong', '', item.name));
        const buttons = node('div', 'button-row');
        for (const file of item.files) {
          if (file.available) { const anchor = node('a', 'action', file.name); anchor.href = file.siteUrl; anchor.download = file.name; buttons.append(anchor); }
          else buttons.append(node('span', 'muted', file.name + ' · 배포 파일 준비 중'));
        }
        record.append(buttons); programs.append(record);
      }
    }
    if (keysPage) renderKeys(keys.keys);
    if (rentalsPage) {
      byId('approval-badge').textContent = services.autoApproved ? '자동 승인 계정' : '관리자 승인 필요';
      byId('rental-policy').textContent = (services.autoApproved ? '승인된 계정입니다. 신청하면 서버가 자동 생성됩니다.' : '신청 후 관리자가 승인하면 서버가 자동 생성됩니다.') + ` 계정당 1개, 전체 최대 ${services.capacity}개입니다. ${services.runtime.message}`;
      const list = byId('rental-list'); list.replaceChildren();
      if (!rentals.rentals.length) list.append(node('p', 'empty', '아직 신청한 워크스페이스가 없습니다.'));
      rentals.rentals.forEach(row => list.append(rentalRecord(row)));
      const busy = rentals.rentals.some(row => !terminal.has(row.status));
      byId('rental-form').querySelectorAll('input,textarea,button').forEach(n => n.disabled = busy);
    }
  }
  async function loadAdmin() {
    const owner = session.user?.id;
    if (!session.user?.isAdmin) return;
    const data = await api('/api/admin/overview?q=' + encodeURIComponent(search));
    if (session.user?.id !== owner || !session.user?.isAdmin) return;
    const list = byId('admin-rentals'); list.replaceChildren();
    byId('admin-runtime').textContent = `${data.runtime.message} · 전체 대여 한도 ${data.capacity}개`;
    if (!data.rentals.length) list.append(node('p', 'empty', '접수된 대여 신청이 없습니다.'));
    data.rentals.forEach(row => list.append(rentalRecord(row, true)));
    const users = byId('admin-users'); users.replaceChildren();
    if (!data.users.length) users.append(node('p', 'empty', '검색된 회원이 없습니다.'));
    for (const row of data.users) {
      const record = node('article', 'record');
      record.append(node('strong', '', row.display_name), node('span', 'pill', row.isAdmin ? '관리자' : row.auto_approved ? '자동 승인' : '신청별 승인'));
      const verified = Boolean(row.email_verified_at && row.registration_completed_at);
      record.append(node('p', 'meta', `회원 ID ${row.id} · ${row.providers || '이메일 가입'} · 가입 ${date(row.created_at)} · ${verified ? '이메일 인증·가입 완료' : '인증·가입 미완료'}`));
      if (row.email) record.append(node('p', 'meta', `${row.email}${row.full_name ? ` · 이름 ${row.full_name}` : ''}`));
      if (!row.isAdmin && (verified || row.auto_approved)) record.append(action(row.auto_approved ? '자동 승인 해제' : '계정 자동 승인', async () => {
        if (!row.auto_approved && !window.confirm(`“${row.display_name}” 계정을 자동 승인할까요? 현재 대기 중인 신청과 앞으로의 신청이 자원 한도 안에서 자동 생성됩니다.`)) return;
        await api(`/api/admin/users/${row.id}/rental-access`, {method: 'POST', body: JSON.stringify({approved: !row.auto_approved})});
        await loadAdmin(); message('계정의 자동 승인 설정을 변경했습니다.');
      }));
      users.append(record);
    }
    await loadPrivacyRequests();
  }
  let privacyList;
  if (adminPage) {
    const panel = node('section', 'panel');
    const heading = node('div', 'panel-heading');
    heading.append(node('h2', '', '개인정보 요청'));
    heading.append(action('새로고침', () => loadPrivacyRequests()));
    panel.append(heading, node('p', 'muted', '자료 열람·삭제 요청은 관리자에게만 보입니다. “완료”는 실제 자료 전달 또는 삭제를 마친 뒤에만 표시하세요. 상태 변경만으로 자료가 삭제되지는 않습니다.'));
    privacyList = node('div', 'record-list'); privacyList.id = 'admin-privacy-requests';
    panel.append(privacyList); byId('admin-content').append(panel);
  }
  async function loadPrivacyRequests() {
    if (!adminPage || !session.user?.isAdmin) return;
    const owner = session.user.id;
    const data = await api('/api/admin/privacy-requests');
    if (session.user?.id !== owner || !session.user?.isAdmin) return;
    privacyList.replaceChildren();
    if (!data.requests.length) privacyList.append(node('p', 'empty', '접수된 정보 요청이 없습니다.'));
    const kinds = {export: '자료 열람·내보내기', delete: '계정·관련 자료 삭제'};
    const states = {pending: '접수됨', acknowledged: '검토 중', completed: '처리 완료', rejected: '처리 불가'};
    for (const row of data.requests) {
      const record = node('article', 'record');
      record.append(node('strong', '', kinds[row.kind] || row.kind), node('span', 'pill', states[row.status] || row.status));
      record.append(node('p', 'meta', `${row.email} · 접수 ${date(row.created_at)} · 갱신 ${date(row.updated_at)}`));
      if (row.message) { const note = node('p', '', row.message); note.style.whiteSpace = 'pre-wrap'; record.append(note); }
      if (row.status === 'pending' || row.status === 'acknowledged') {
        const buttons = node('div', 'button-row');
        async function review(status) {
          await api(`/api/admin/privacy-requests/${row.id}/review`, {method: 'POST', body: JSON.stringify({status})});
          await loadPrivacyRequests(); message('정보 요청 상태를 갱신했습니다.');
        }
        if (row.status === 'pending') buttons.append(action('접수 확인', () => review('acknowledged')));
        buttons.append(action('실제 처리 후 완료', async () => {
          if (!window.confirm('요청한 자료 전달 또는 계정 자료 삭제를 실제로 마쳤나요? 상태만 완료로 바꿔도 자료는 자동 삭제되지 않습니다.')) return;
          await review('completed');
        }));
        buttons.append(action('처리 불가', async () => {
          if (!window.confirm('이 요청을 처리 불가로 표시할까요? 요청자에게는 상태만 표시됩니다. 사유는 별도 연락으로 알려주세요.')) return;
          await review('rejected');
        }, true));
        record.append(buttons);
      }
      privacyList.append(record);
    }
  }
  async function refresh(next = window.habangSession) {
    const current = ++epoch;
    try {
      if (!next) return;
      if (current !== epoch) return;
      if (next.user?.id !== session.user?.id) clearSecret();
      session = next;
      const complete = Boolean(session.user?.verified && session.user?.registrationComplete);
      if (!complete) clearSecret();
      byId('portal-guest').hidden = complete;
      byId('portal-login').textContent = session.user ? '인증·가입 완료하기' : '로그인 · 회원가입';
      const content = byId(adminPage ? 'admin-content' : 'member-content');
      content.hidden = !complete || (adminPage && !session.user.isAdmin);
      if (!session.user) { message('로그인 후 서비스를 이용할 수 있습니다.'); return; }
      if (!complete) { message('Google·GitHub로 이메일을 확인하고 회원가입을 완료한 뒤 이용해 주세요.', true); return; }
      if (adminPage && !session.user.isAdmin) { message('이 계정에는 관리자 권한이 없습니다.', true); return; }
      await (adminPage ? loadAdmin() : loadMember());
      if (current === epoch) message(adminPage ? '승인과 서버 상태를 관리할 수 있습니다.' : `${session.user.name}님의 서비스입니다.`);
    } catch (error) { if (current === epoch) message(error.message, true); }
  }
  byId('portal-login').addEventListener('click', () => window.dispatchEvent(new Event(session.user ? 'habang:register' : 'habang:login')));
  if (keysPage) {
    byId('key-form').addEventListener('submit', async event => {
      event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
      try {
        const values = new FormData(form);
        const result = await api('/api/keys', {method: 'POST', body: JSON.stringify({name: values.get('name'), days: Number(values.get('days')), program: values.get('program')})});
        byId('key-secret').textContent = result.secret; byId('key-once').hidden = false;
        form.querySelector('[name=name]').value = ''; await loadMember(); message('API 키를 발급했습니다. 표시된 원문을 지금 보관해 주세요.');
      } catch (error) { message(error.message, true); } finally { button.disabled = false; }
    });
    byId('copy-key').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(byId('key-secret').textContent); message('API 키를 복사했습니다.'); }
      catch { message('자동 복사가 지원되지 않습니다. 표시된 키를 직접 선택해 복사해 주세요.', true); }
    });
    byId('dismiss-key').addEventListener('click', clearSecret);
  }
  if (rentalsPage) {
    byId('rental-form').addEventListener('submit', async event => {
      event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
      try {
        const values = new FormData(form);
        const result = await api('/api/rentals', {method: 'POST', body: JSON.stringify({name: values.get('name'), publicKey: values.get('publicKey')})});
        form.reset(); await loadMember(); message(result.rental.status === 'pending' ? '신청을 접수했습니다. 관리자 승인을 기다려 주세요.' : '신청을 접수했습니다. 서버를 자동 생성합니다.');
      } catch (error) { message(error.message, true); button.disabled = false; }
    });
    byId('refresh-rentals').addEventListener('click', () => loadMember().catch(error => message(error.message, true)));
  }
  if (adminPage) {
    byId('refresh-admin').addEventListener('click', () => loadAdmin().catch(error => message(error.message, true)));
    byId('user-search').addEventListener('submit', event => { event.preventDefault(); search = new FormData(event.currentTarget).get('q'); loadAdmin().catch(error => message(error.message, true)); });
  }
  function renderExamples() {
    const item = programCatalog.find(p => p.id === byId('guide-program').value);
    if (!item) return;
    const continued = ' ' + String.fromCharCode(92, 10);
    byId('download-example').textContent = [`curl --fail --output "${item.defaultFile}"`, '  --header "Authorization: Bearer 내_API_키"', `  https://habang222.pro/api/v1/programs/${item.id}/download`].join(continued);
    byId('metadata-example').textContent = ['curl --fail --header "Authorization: Bearer 내_API_키"', `  https://habang222.pro/api/v1/programs/${item.id}`].join(continued);
  }
  window.addEventListener('habang:session', event => { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => refresh(event.detail), 50); });
  window.addEventListener('pagehide', clearSecret);
  setInterval(() => { if (!document.hidden && session.user) (adminPage ? loadAdmin() : loadMember()).catch(() => {}); }, 10000);
  refresh();
})();
