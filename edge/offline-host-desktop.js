(() => {
  const status = document.getElementById('desktop-status');
  if (status) status.textContent = '서버 연결이 복구되면 Kali 원격 접속을 이용할 수 있습니다.';
  for (const form of document.querySelectorAll('form')) form.hidden = true;
  for (const button of document.querySelectorAll('button')) button.disabled = true;
})();
