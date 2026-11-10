# 정적 페이지 장애 전환

`failover-worker.mjs`는 Cloudflare의 `habang222.pro/*` Worker Route에 설치한다.
기존 주황색 프록시 DNS 레코드는 Cloudflare Tunnel을 계속 가리킨다. Cloudflare
문서상 Route Worker의 `fetch(request)`는 DNS에 설정된 원 서버로 요청을 보낸다.
따라서 정상 서버의 응답을 그대로 돌려주며, 5xx 또는 연결 오류일 때만 GitHub
Pages의 별도 공개 정적 저장소를 가져온다.

GitHub Pages는 공개 저장소 `habang2222/habang222-pages`의 `main` 루트를 게시한다.
백업 URL은 `https://habang2222.github.io/habang222-pages/`이다. 이 저장소는
기존 사이트 소스 저장소의 Git 기록을 복제하지 않고, `build-fallback.mjs`가
만든 최상위 HTML/CSS/JS와 `images/`만 넣는다. `downloads/`, 서버 코드,
설정 파일, DB는 포함하지 않는다. 사용자 지정 도메인은 설정하지 않는다.

Windows PowerShell에서 `edge/publish-public-pages.ps1`을 실행하면 현재 소스에서
정적 파일을 생성하고, 허용되지 않은 파일 형식을 검사한 뒤 별도 공개 저장소에
반영한다. GitHub CLI 또는 Git 자격 증명으로 `habang2222` 계정에 push할 수
있어야 한다. 공개 저장소의 사람 계정 push는 Pages 브랜치 배포를 시작한다.
화면을 수정할 때 이 스크립트를 다시 실행하고 Pages 게시 상태와 공개 URL을
확인한다. 자동 장애 전환 자체는 Cloudflare Worker가 처리한다.

Worker는 인증·API·다운로드 경로를 GitHub Pages로 우회시키지 않는다. 서버가
꺼졌을 때 이 경로는 503이며, HTML에는 서비스 중단 안내가 표시된다. 브라우저
캐시가 서버 복구를 가리지 않도록 백업 응답에 `Cache-Control: no-store`를
붙인다. 서버 응답의 401·403·404는 정상 응답으로 취급하여 백업으로 전환하지
않는다. Pages 요청에는 방문자의 Cookie·Authorization 헤더·쿼리를 전달하지
않는다.

로컬 단위 테스트: `node --test tests/failover-worker.test.mjs`

Cloudflare 문서: https://developers.cloudflare.com/workers/configuration/routing/routes/
GitHub Pages 문서: https://docs.github.com/en/rest/pages/pages
