(() => {
  'use strict';
  const status = document.getElementById('privacy-request-status');
  if (status) status.textContent = '서버가 연결되면 본인 정보 요청과 처리 상태를 확인할 수 있습니다. 일반 문의는 위 지원 이메일을 이용해 주세요.';
  const guest = document.getElementById('privacy-request-guest');
  if (guest) guest.hidden = true;
  const form = document.getElementById('privacy-request-form');
  if (form) form.hidden = true;
})();
