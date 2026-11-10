(() => {
  'use strict';
  const page = location.pathname === '/index.html' ? '/' : location.pathname;
  let state = {user: null, csrfToken: '', providers: {}, pendingRegistration: null, emailVerificationAvailable: false};
  let nextBefore = null;
  let mode = 'login';
  let ready = false;
  let lastFocus = null;
  function resumeDownload() {
    if (!state.user?.verified || !state.user?.registrationComplete) return;
    const path = sessionStorage.getItem('habang:download');
    sessionStorage.removeItem('habang:download');
    if (path && /^\/downloads\/[A-Za-z0-9_.-]+$/.test(path)) location.assign(path);
  }
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href]');
    if (!anchor) return;
    const url = new URL(anchor.href, location.href);
    if (url.origin === location.origin && /^\/downloads\/[A-Za-z0-9_.-]+$/.test(url.pathname) && url.pathname !== '/downloads/manifest.json' && (!state.user?.verified || !state.user?.registrationComplete)) {
      event.preventDefault(); sessionStorage.setItem('habang:download', url.pathname); showAuth(state.user ? 'register' : 'login');
    }
  });
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const button = (label, action, className = 'hb-button') => {
    const b = el('button', className, label); b.type = 'button'; b.addEventListener('click', action); return b;
  };
  async function api(path, options = {}) {
    const res = await fetch(path, {credentials: 'same-origin', ...options, headers: {
      ...(options.body ? {'Content-Type': 'application/json', 'X-CSRF-Token': state.csrfToken} : {}),
      ...options.headers
    }});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '요청을 처리하지 못했습니다. 다시 시도해 주세요.');
    return data;
  }
  const toolbar = el('nav', 'hb-toolbar');
  toolbar.setAttribute('aria-label', '회원 메뉴');
  const account = el('span', 'hb-account');
  const homeLink = el('a', 'hb-header-brand', 'habang222'); homeLink.href = '/';
  const apiLink = el('a', 'hb-link', 'API 키'); apiLink.href = '/api.html';
  const rentalsLink = el('a', 'hb-link', '서버 대여'); rentalsLink.href = '/servers.html';
  const adminLink = el('a', 'hb-link', '관리자'); adminLink.href = '/admin.html'; adminLink.hidden = true;
  for (const link of [apiLink, rentalsLink, adminLink]) {
    if (link.getAttribute('href') === page) link.setAttribute('aria-current', 'page');
  }
  toolbar.append(homeLink, apiLink, rentalsLink, adminLink);
  toolbar.append(account);
  const loginButton = button('로그인 · 회원가입', () => showAuth('login'));
  toolbar.append(loginButton);
  const siteHeader = el('header', 'hb-site-header');
  siteHeader.append(toolbar);
  document.body.prepend(siteHeader);

  const dialog = el('dialog', 'hb-dialog');
  dialog.setAttribute('aria-labelledby', 'hb-auth-title');
  const close = button('닫기 ×', () => dialog.close(), 'hb-link hb-dialog-close');
  const title = el('h2', '', '다시 만나서 반가워요'); title.id = 'hb-auth-title';
  const intro = el('p', 'hb-muted', '로그인하고 이야기를 나눠보세요.');
  const tabs = el('div', 'hb-tabs');
  const loginTab = button('로그인', () => setMode('login'));
  const registerTab = button('회원가입', () => setMode('register'));
  tabs.append(loginTab, registerTab);
  const social = el('div', 'hb-social');
  const providerLinks = {};
  for (const [key, label, mark] of [['google', 'Google로 계속하기', 'G'], ['github', 'GitHub로 계속하기', '◉']]) {
    const a = el('a', 'hb-provider');
    a.append(el('span', 'hb-provider-mark', mark), el('span', '', label));
    a.href = `/auth/${key}?next=${encodeURIComponent(page)}`;
    a.addEventListener('click', async event => {
      if (!state.providers[key]) { event.preventDefault(); authStatus.textContent = '아직 준비 중인 인증 방식입니다.'; return; }
      if (state.user) {
        event.preventDefault();
        try {
          const result = await api(`/api/auth/link/${key}`, {method: 'POST', body: JSON.stringify({next: page})});
          location.assign(result.url);
        } catch (error) { authStatus.textContent = error.message; }
      }
    });
    providerLinks[key] = a; social.append(a);
  }
  const divider = el('p', 'hb-divider', '또는 이메일로 로그인');
  const verification = el('div', 'hb-form');
  const verificationEmailLabel = el('label', 'hb-field', '인증할 이메일');
  const verificationEmail = el('input'); verificationEmail.type = 'email'; verificationEmail.autocomplete = 'email'; verificationEmail.maxLength = 254;
  verificationEmailLabel.append(verificationEmail);
  const sendCode = button('인증 코드 보내기', async () => {
    sendCode.disabled = true; authStatus.textContent = '인증 메일을 보내는 중…';
    try {
      await api('/api/auth/email/start', {method: 'POST', body: JSON.stringify({email: verificationEmail.value})});
      verificationCode.hidden = false; authStatus.textContent = '메일로 받은 8자리 코드를 입력해 주세요.';
    } catch (error) { authStatus.textContent = error.message; }
    finally { sendCode.disabled = false; }
  });
  const verificationCode = el('div', 'hb-form'); verificationCode.hidden = true;
  const codeLabel = el('label', 'hb-field', '8자리 인증 코드');
  const codeInput = el('input'); codeInput.inputMode = 'numeric'; codeInput.pattern = '[0-9]{8}'; codeInput.maxLength = 8;
  codeLabel.append(codeInput);
  const verifyCode = button('이메일 확인', async () => {
    verifyCode.disabled = true; authStatus.textContent = '인증 코드를 확인하는 중…';
    try {
      const result = await api('/api/auth/email/verify', {method: 'POST', body: JSON.stringify({email: verificationEmail.value, code: codeInput.value})});
      state = {...state, ...result}; setMode('register'); authStatus.textContent = '이메일이 확인되었습니다. 회원 정보를 입력해 주세요.';
    } catch (error) { authStatus.textContent = error.message; }
    finally { verifyCode.disabled = false; }
  });
  verificationCode.append(codeLabel, verifyCode);
  verification.append(verificationEmailLabel, sendCode, verificationCode);
  const form = el('form', 'hb-form');
  function field(labelText, name, type, autocomplete) {
    const wrap = el('label', 'hb-field', labelText);
    const input = el('input'); input.name = name; input.type = type; input.autocomplete = autocomplete;
    input.required = true; wrap.append(input); form.append(wrap); return [wrap, input];
  }
  const [nameWrap, nameInput] = field('닉네임', 'name', 'text', 'nickname');
  nameInput.minLength = 2; nameInput.maxLength = 30;
  const [fullNameWrap, fullNameInput] = field('이름', 'fullName', 'text', 'name');
  fullNameInput.minLength = 2; fullNameInput.maxLength = 60;
  const [, emailInput] = field('이메일', 'email', 'email', 'email'); emailInput.maxLength = 254;
  const [, passwordInput] = field('비밀번호', 'password', 'password', 'current-password'); passwordInput.maxLength = 128;
  const passwordHint = el('p', 'hb-muted', '비밀번호는 12~128자로 입력해 주세요.');
  const submit = el('button', 'hb-button hb-primary', '로그인'); submit.type = 'submit';
  const authStatus = el('p', 'hb-status'); authStatus.setAttribute('role', 'status');
  form.append(passwordHint, submit);
  dialog.append(close, title, intro, tabs, social, verification, divider, form, authStatus);
  document.body.append(dialog);
  dialog.addEventListener('close', () => lastFocus?.focus());
  dialog.addEventListener('click', e => {
    if (e.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) dialog.close();
    }
  });
  function setMode(value) {
    mode = value;
    const signingUp = mode === 'register';
    const proof = state.pendingRegistration;
    nameWrap.hidden = !signingUp; nameInput.required = signingUp; nameInput.disabled = !signingUp;
    fullNameWrap.hidden = !signingUp; fullNameInput.required = signingUp; fullNameInput.disabled = !signingUp;
    verification.hidden = !signingUp || Boolean(proof) || !state.emailVerificationAvailable;
    form.hidden = signingUp && !proof;
    emailInput.readOnly = signingUp;
    if (signingUp) {
      emailInput.value = proof?.email || '';
      if (proof?.suggestedName && !nameInput.value) nameInput.value = proof.suggestedName;
      verificationEmail.value = state.user?.email || verificationEmail.value;
    }
    title.textContent = signingUp ? 'habang 회원이 되어보세요' : '다시 만나서 반가워요';
    intro.textContent = signingUp ? (proof ? '인증된 이메일을 아이디로 사용합니다. 비밀번호, 닉네임, 이름을 등록해 주세요.' : state.user?.registrationComplete ? '현재 계정에 Google 또는 GitHub를 연결하세요. 연결 전에는 최근 10분 이내 비밀번호 로그인이 필요합니다.' : 'Google 또는 GitHub로 이메일을 먼저 확인해 주세요.') : '로그인하고 이야기를 나눠보세요.';
    divider.textContent = signingUp ? (proof ? '회원 정보 등록' : '이메일 인증') : '또는 이메일로 로그인';
    divider.hidden = signingUp && !proof && !state.emailVerificationAvailable;
    submit.textContent = signingUp ? '회원가입' : '로그인';
    passwordHint.hidden = !signingUp;
    passwordInput.minLength = signingUp ? 12 : 1;
    passwordInput.autocomplete = signingUp ? 'new-password' : 'current-password';
    loginTab.setAttribute('aria-pressed', String(!signingUp));
    registerTab.setAttribute('aria-pressed', String(signingUp));
    authStatus.textContent = '';
  }
  function showAuth(value) {
    setMode(value); lastFocus = document.activeElement;
    if (!ready) authStatus.textContent = '로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.';
    if (!dialog.open) dialog.showModal();
    (mode === 'register' ? (state.pendingRegistration ? nameInput : state.emailVerificationAvailable ? verificationEmail : social.querySelector('a')) : emailInput).focus();
  }
  form.addEventListener('submit', async e => {
    e.preventDefault(); if (submit.disabled) return;
    submit.disabled = true; authStatus.textContent = '처리 중…';
    try {
      if (!ready) { state = await api('/api/session'); ready = true; }
      const data = await api(`/api/auth/${mode}`, {method: 'POST', body: JSON.stringify({
        name: nameInput.value, fullName: fullNameInput.value, email: emailInput.value, password: passwordInput.value
      })});
      state = {...state, ...data, pendingRegistration: null}; form.reset(); dialog.close(); renderAccount();
      status.textContent = mode === 'register' ? '회원가입이 완료되었습니다.' : '로그인되었습니다.';
      await loadComments();
      if (state.user && (!state.user.verified || !state.user.registrationComplete)) showAuth('register');
      else resumeDownload();
    } catch (err) { authStatus.textContent = err.message; }
    finally { submit.disabled = false; }
  });

  const section = el('section', 'hb-community');
  section.setAttribute('aria-labelledby', 'hb-comments-title');
  const heading = el('div', 'hb-comment-heading');
  const commentsTitle = el('h2', '', '댓글'); commentsTitle.id = 'hb-comments-title';
  const count = el('span', 'hb-count', '0'); heading.append(commentsTitle, count);
  const description = el('p', 'hb-muted', '이 페이지에 대한 질문이나 의견을 남겨주세요.');
  const composer = el('form', 'hb-composer');
  const commentLabel = el('label', 'hb-comment-label', '댓글 작성'); commentLabel.htmlFor = 'hb-comment-body';
  const textarea = el('textarea'); textarea.id = 'hb-comment-body'; textarea.rows = 4;
  textarea.maxLength = 2000; textarea.required = true; textarea.placeholder = '함께 나누고 싶은 이야기를 적어주세요.';
  const composeActions = el('div', 'hb-compose-actions');
  const charCount = el('span', 'hb-muted', '0 / 2,000');
  textarea.addEventListener('input', () => charCount.textContent = `${textarea.value.length.toLocaleString()} / 2,000`);
  const postButton = el('button', 'hb-button hb-primary', '댓글 등록'); postButton.type = 'submit';
  composeActions.append(charCount, postButton); composer.append(commentLabel, textarea, composeActions);
  const guest = el('div', 'hb-guest'); guest.append(el('span', '', '댓글을 작성하려면 로그인해 주세요.'), button('로그인 / 회원가입', () => showAuth('login')));
  const status = el('p', 'hb-status'); status.setAttribute('role', 'status');
  const list = el('div', 'hb-comments');
  const more = button('댓글 더 보기', () => loadComments(true)); more.hidden = true;
  section.append(heading, description, guest, composer, status, list, more);
  const footer = document.querySelector('body > footer, .page-shell > footer');
  if (footer) footer.before(section); else document.querySelector('main')?.after(section);

  function renderAccount() {
    const complete = Boolean(state.user?.verified && state.user?.registrationComplete);
    adminLink.hidden = !state.user?.isAdmin || !complete;
    if (ready) {
      window.habangSession = {...state};
      window.dispatchEvent(new CustomEvent('habang:session', {detail: window.habangSession}));
    }
    toolbar.querySelectorAll('[data-logout]').forEach(n => n.remove());
    toolbar.querySelectorAll('[data-onboarding]').forEach(n => n.remove());
    account.textContent = state.user ? `${state.user.name}님${complete ? '' : ' · 가입 확인 필요'}` : '';
    loginButton.hidden = Boolean(state.user);
    composer.hidden = !state.user; guest.hidden = Boolean(state.user);
    if (state.user) {
      if (!complete) {
        const finish = button('인증·가입 완료', () => showAuth('register'), 'hb-link');
        finish.dataset.onboarding = ''; toolbar.append(finish);
      } else {
        const connect = button('소셜 계정 연결', () => showAuth('register'), 'hb-link');
        connect.dataset.onboarding = ''; toolbar.append(connect);
      }
      const logout = button('로그아웃', async () => {
        logout.disabled = true;
        try {
          state = {...state, ...await api('/api/auth/logout', {method: 'POST', body: '{}'})};
          renderAccount(); await loadComments(); status.textContent = '로그아웃되었습니다.';
        } catch (err) { status.textContent = err.message; logout.disabled = false; }
      }, 'hb-link'); logout.dataset.logout = ''; toolbar.append(logout);
    }
    for (const [key, a] of Object.entries(providerLinks)) {
      a.setAttribute('aria-disabled', String(!state.providers[key]));
      a.title = state.providers[key] ? '' : '이 로그인 방식은 현재 준비 중입니다.';
      a.lastChild.textContent = state.user ? `${key === 'google' ? 'Google' : 'GitHub'} 인증·계정 연결` : `${key === 'google' ? 'Google' : 'GitHub'}로 계속하기`;
    }
  }
  function commentNode(comment) {
    const article = el('article', 'hb-comment');
    const head = el('div', 'hb-comment-meta');
    const avatar = el('span', 'hb-avatar', Array.from(comment.author)[0] || 'H'); avatar.setAttribute('aria-hidden', 'true');
    const meta = el('div'); const author = el('strong', '', comment.author);
    const time = el('time'); time.dateTime = new Date(comment.createdAt * 1000).toISOString();
    time.textContent = new Intl.DateTimeFormat('ko-KR', {dateStyle: 'medium', timeStyle: 'short'}).format(comment.createdAt * 1000) + (comment.updatedAt > comment.createdAt ? ' · 수정됨' : '');
    meta.append(author, time); head.append(avatar, meta);
    const body = el('p', 'hb-comment-body', comment.body);
    const actions = el('div', 'hb-comment-actions');
    if (comment.canEdit) actions.append(button('수정', () => {
      const edit = el('form', 'hb-edit');
      const input = el('textarea'); input.rows = 4; input.maxLength = 2000; input.required = true; input.value = comment.body;
      input.setAttribute('aria-label', '댓글 수정');
      const save = el('button', 'hb-button hb-primary', '저장'); save.type = 'submit';
      edit.append(input, save, button('취소', () => { edit.remove(); body.hidden = false; actions.hidden = false; }));
      body.hidden = true; actions.hidden = true; article.append(edit); input.focus();
      edit.addEventListener('submit', async e => {
        e.preventDefault(); save.disabled = true;
        try {
          const data = await api(`/api/comments/${comment.id}`, {method: 'PATCH', body: JSON.stringify({body: input.value})});
          article.replaceWith(commentNode(data.comment)); status.textContent = '댓글을 수정했습니다.';
        } catch (err) { status.textContent = err.message; save.disabled = false; }
      });
    }, 'hb-link'));
    if (comment.canDelete) actions.append(button('삭제', async () => {
      if (!window.confirm('이 댓글을 삭제할까요?')) return;
      try {
        await api(`/api/comments/${comment.id}`, {method: 'DELETE', body: '{}'});
        await loadComments(); status.textContent = '댓글을 삭제했습니다.';
      } catch (err) { status.textContent = err.message; }
    }, 'hb-link'));
    article.append(head, body, actions); return article;
  }
  async function loadComments(append = false) {
    more.disabled = true;
    try {
      const data = await api(`/api/comments?page=${encodeURIComponent(page)}${append && nextBefore ? `&before=${nextBefore}` : ''}`);
      if (!append) list.replaceChildren();
      count.textContent = data.total.toLocaleString();
      if (!data.total) list.append(el('p', 'hb-empty', '첫 번째 댓글을 남겨보세요.'));
      data.comments.forEach(comment => list.append(commentNode(comment)));
      nextBefore = data.nextBefore; more.hidden = !nextBefore;
    } catch (err) { status.textContent = '댓글을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'; }
    finally { more.disabled = false; }
  }
  composer.addEventListener('submit', async e => {
    e.preventDefault(); if (!textarea.value.trim() || postButton.disabled) return;
    postButton.disabled = true;
    try {
      await api('/api/comments', {method: 'POST', body: JSON.stringify({page, body: textarea.value})});
      textarea.value = ''; charCount.textContent = '0 / 2,000'; await loadComments(); status.textContent = '댓글을 등록했습니다.';
    } catch (err) { status.textContent = err.message; }
    finally { postButton.disabled = false; }
  });
  async function init() {
    renderAccount(); status.textContent = '댓글을 불러오는 중…';
    try {
      state = await api('/api/session'); ready = true; renderAccount(); status.textContent = '';
      await loadComments();
      resumeDownload();
      if (state.pendingRegistration || (state.user && (!state.user.verified || !state.user.registrationComplete))) showAuth('register');
    } catch (err) { status.textContent = '로그인·댓글 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.'; }
    const url = new URL(location.href); const error = url.searchParams.get('auth_error');
    const linked = url.searchParams.get('auth_linked');
    if (linked === 'google' || linked === 'github') {
      showAuth('register');
      authStatus.textContent = `${linked === 'google' ? 'Google' : 'GitHub'} 계정 연결이 완료되었습니다.`;
      url.searchParams.delete('auth_linked'); history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
    if (error) {
      showAuth(error === 'account_conflict' || error === 'reauth_required' ? 'login' : 'register');
      authStatus.textContent = error === 'unavailable' ? '아직 준비 중인 로그인 방식입니다.' : error === 'account_conflict' ? '기존 이메일 계정에 비밀번호로 로그인한 뒤 Google 또는 GitHub 인증·계정 연결을 진행해 주세요.' : error === 'link_conflict' ? '이전 소셜 계정에 별도 데이터나 권한이 있어 자동 연결할 수 없습니다. 관리자에게 문의해 주세요.' : error === 'reauth_required' ? '계정 연결 전 비밀번호로 다시 로그인해 주세요.' : '소셜 인증을 완료하지 못했습니다. 다시 시도해 주세요.';
      url.searchParams.delete('auth_error'); history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
  }
  window.addEventListener('habang:login', () => showAuth('login'));
  window.addEventListener('habang:register', () => showAuth('register'));
  init();
})();
