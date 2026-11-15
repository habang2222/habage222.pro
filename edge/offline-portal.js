(() => {
  'use strict';
  const root = document.querySelector('[data-portal]');
  if (!root) return;
  for (const form of root.querySelectorAll('form')) form.hidden = true;
  for (const button of root.querySelectorAll('button')) button.disabled = true;
  const status = document.getElementById('portal-status');
  if (status) status.textContent = '서버 연결이 복구되면 이 기능을 다시 이용할 수 있습니다.';
})();
