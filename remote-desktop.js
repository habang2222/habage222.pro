(() => {
  'use strict';
  const panel = document.getElementById('desktop-screen');
  if (!panel) return;
  const form = document.getElementById('remote-connect');
  const viewport = document.getElementById('remote-viewport');
  const notice = document.getElementById('remote-status');
  const connectButton = form.querySelector('button');
  const disconnectButton = document.getElementById('remote-disconnect');
  const password = form.elements.password;
  let session = null, client = null, keyboard = null, connected = false, timer = null;

  function message(text, error = false) {
    notice.textContent = text;
    notice.classList.toggle('error', error);
  }
  function stop(text = '연결을 종료했습니다.') {
    clearTimeout(timer);
    const previous = client; client = null; connected = false;
    if (keyboard) { keyboard.reset(); keyboard = null; }
    if (previous) previous.disconnect();
    connectButton.disabled = false; disconnectButton.disabled = true;
    form.hidden = false; password.value = '';
    viewport.replaceChildren(); viewport.classList.remove('is-connected');
    if (text) message(text);
  }
  function makeTunnel(credentials) {
    const tunnel = new Guacamole.Tunnel();
    let socket = null;
    tunnel.connect = () => {
      tunnel.setState(Guacamole.Tunnel.State.CONNECTING);
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/remote/host`, 'guacamole');
      const parser = new Guacamole.Parser();
      parser.oninstruction = (opcode, args) => {
        if (tunnel.state !== Guacamole.Tunnel.State.OPEN) tunnel.setState(Guacamole.Tunnel.State.OPEN);
        if (tunnel.oninstruction) tunnel.oninstruction(opcode, args);
      };
      socket.onopen = () => { socket.send(JSON.stringify(credentials)); credentials.password = ''; };
      socket.onmessage = event => {
        try { parser.receive(event.data); }
        catch (_) { stop('원격 화면 정보를 처리하지 못했습니다. 다시 연결해 주세요.'); }
      };
      socket.onclose = event => {
        credentials.password = '';
        tunnel.setState(Guacamole.Tunnel.State.CLOSED);
        if (client) stop(event.reason || '연결이 끊겼습니다. 다시 연결해 주세요.');
      };
      socket.onerror = () => { credentials.password = ''; message('연결을 확인하고 있습니다…'); };
    };
    tunnel.sendMessage = (...args) => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(Guacamole.Parser.toInstruction(args));
    };
    tunnel.disconnect = () => {
      credentials.password = '';
      if (socket) { socket.onclose = null; socket.close(1000); }
      tunnel.setState(Guacamole.Tunnel.State.CLOSED);
    };
    return tunnel;
  }
  function fit() {
    if (!client) return;
    const display = client.getDisplay();
    const width = display.getWidth(), height = display.getHeight();
    if (width && height) display.scale(Math.min(viewport.clientWidth / width, viewport.clientHeight / height));
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (client || !session?.user?.verified || !session.user.registrationComplete) return;
    connectButton.disabled = true;
    message('로그인과 접속 승인을 확인하고 Kali 화면을 여는 중입니다…');
    try {
      const response = await fetch('/api/session', {credentials:'same-origin', cache:'no-store'});
      const next = await response.json();
      if (!response.ok || next.user?.id !== session.user.id) throw new Error('다시 로그인해 주세요.');
      session = next;
      const resolution = form.elements.resolution.value.split('x').map(Number);
      client = new Guacamole.Client(makeTunnel({csrfToken:session.csrfToken, password:password.value,
        width:resolution[0], height:resolution[1]}));
      password.value = '';
      const display = client.getDisplay();
      const element = display.getElement();
      const input = document.createElement('div'); input.className = 'remote-input'; input.tabIndex = 0;
      input.setAttribute('aria-label','원격 Kali 작업 화면. 클릭하면 키보드와 마우스를 사용할 수 있습니다.');
      input.append(element); viewport.replaceChildren(input);
      keyboard = new Guacamole.Keyboard(input);
      keyboard.onkeydown = keysym => { client?.sendKeyEvent(1, keysym); return false; };
      keyboard.onkeyup = keysym => client?.sendKeyEvent(0, keysym);
      input.addEventListener('blur', () => keyboard?.reset());
      input.addEventListener('pointerdown', () => input.focus({preventScroll:true}));
      const mouse = new Guacamole.Mouse(element);
      const touch = new Guacamole.Mouse.Touchscreen(element);
      for (const source of [mouse, touch]) source.onEach(['mousedown','mousemove','mouseup'], event => {
        client?.sendMouseState(event.state, true);
      });
      display.onresize = fit;
      client.onerror = () => {
        stop(); message('Kali에 로그인하지 못했습니다. 신청할 때 정한 원격 비밀번호를 확인해 주세요.', true);
      };
      client.onstatechange = state => {
        if (state === Guacamole.Client.State.CONNECTED) {
          clearTimeout(timer); connected = true; form.hidden = true;
          viewport.classList.add('is-connected'); disconnectButton.disabled = false;
          message('연결됨 · 화면을 클릭하면 조작할 수 있습니다.'); fit(); input.focus({preventScroll:true});
        }
      };
      disconnectButton.disabled = false;
      timer = setTimeout(() => { if (!connected) stop('화면 준비 시간이 길어졌습니다. 비밀번호를 확인하고 다시 연결해 주세요.'); }, 60000);
      client.connect();
    } catch (error) { stop(); message(error.message || '연결하지 못했습니다.', true); }
  });
  disconnectButton.addEventListener('click', () => stop());
  document.getElementById('remote-fullscreen').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await panel.requestFullscreen();
    } catch (_) { message('이 브라우저에서 전체 화면을 사용할 수 없습니다.'); }
  });
  document.getElementById('remote-ctrl-alt-del').addEventListener('click', () => {
    if (!client || !connected) return;
    for (const key of [65507,65513,65535]) client.sendKeyEvent(1,key);
    for (const key of [65535,65513,65507]) client.sendKeyEvent(0,key);
  });
  window.addEventListener('resize',fit);
  document.addEventListener('fullscreenchange', () => requestAnimationFrame(fit));
  window.addEventListener('pagehide', () => stop(''));
  window.HBRemote = {
    update(next, allowed) {
      if (client && (!allowed || next?.user?.id !== session?.user?.id)) stop('접속 권한 또는 로그인이 변경되어 연결을 종료했습니다.');
      session = next; panel.hidden = !allowed;
    },
    show() { panel.scrollIntoView({behavior:'smooth',block:'start'}); if (!client) password.focus({preventScroll:true}); }
  };
})();
