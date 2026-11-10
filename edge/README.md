# 정적 페이지 장애 전환

`failover-worker.mjs`는 Cloudflare의 `habang222.pro/*` Worker Route에 설치한다.
기존 주황색 프록시 DNS 레코드는 Cloudflare Tunnel을 계속 가리킨다. Cloudflare
문서상 Route Worker의 `fetch(request)`는 DNS에 설정된 원 서버로 요청을 보낸다.
따라서 정상 서버의 응답을 그대로 돌려주며, 5xx 또는 연결 오류일 때만 GitHub
Pages의 `fallback-pages` 정적 브랜치를 가져온다.

GitHub Pages는 `fallback-pages` 브랜치 루트를 게시하고 사용자 지정 도메인은
설정하지 않는다. 백업 URL은
`https://habang2222.github.io/habage222.pro/`이다. 기존 Pages의
`habang222.pro` 사용자 지정 도메인을 제거해야 이 URL이 본 도메인으로
리다이렉트되지 않는다. 정적 브랜치에는 최상위 HTML/CSS/JS와 `images/`만
포함하고 `downloads/`, 서버 코드, 설정 파일, DB는 포함하지 않는다.

`publish-fallback.yml`은 메인 또는 현재 기능 브랜치의 화면 파일이 바뀌면
정적 브랜치를 갱신한다. 파일을 GitHub 저장소에 푸시한 직후 GitHub Actions의
성공과 Pages 게시 상태를 확인한다.

Worker는 인증·API·다운로드 경로를 GitHub Pages로 우회시키지 않는다. 서버가
꺼졌을 때 이 경로는 503이며, HTML에는 서비스 중단 안내가 표시된다. 브라우저
캐시가 서버 복구를 가리지 않도록 백업 응답에 `Cache-Control: no-store`를
붙인다. 서버 응답의 401·403·404는 정상 응답으로 취급하여 백업으로 전환하지
않는다. Pages 요청에는 방문자의 Cookie·Authorization 헤더·쿼리를 전달하지
않는다.

로컬 단위 테스트: `node --test tests/failover-worker.test.mjs`

Cloudflare 문서: https://developers.cloudflare.com/workers/configuration/routing/routes/
GitHub Pages 문서: https://docs.github.com/en/rest/pages/pages
