"use strict";
for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const code = document.getElementById(button.dataset.copy);
    const status = document.getElementById("copy-status");
    if (!code || !status) return;
    try {
      await navigator.clipboard.writeText(code.textContent.trim());
      status.textContent = "명령어를 복사했습니다. Ubuntu 터미널에 붙여 넣으세요.";
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(code);
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = "자동 복사를 사용할 수 없습니다. 선택된 명령어를 직접 복사하세요.";
    }
  });
}
