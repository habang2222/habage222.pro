# 로그인 · 회원가입 · 페이지별 댓글

기존 정적 HTML을 Flask 앱에서 함께 제공합니다. SQLite DB는 웹 파일 밖에 저장합니다.
모든 HTML 페이지에 `community.js`와 `community.css`가 연결되어 있습니다.
댓글은 페이지 경로별로 분리되며 `/`와 `/index.html`은 같은 댓글을 사용합니다.

## 실행

Python 3.11 이상이 필요합니다. 서버에서 다음 구조로 배치합니다.

```text
/srv/files/site/    기존 HTML, CSS, JS, images, downloads
/srv/files/app/     app.py, requirements.txt
/srv/files/config/  community.env (권한 600)
/srv/files/data/    community.sqlite3, WAL (권한 700)
/srv/files/venv/    Python 가상환경
```

`.env.example`을 참고해 `community.env`를 작성합니다. 비밀번호, OAuth Secret,
SECRET_KEY, DB 파일은 Git에 올리지 않습니다. `BASE_URL`은 브라우저에서 사용하는
정확한 주소여야 하며 끝의 `/`는 생략합니다. 공개 서비스는 HTTPS를 사용합니다.
`SECRET_KEY`는 최소 32자 이상의 무작위 값입니다.

```sh
python3 -m venv /srv/files/venv
/srv/files/venv/bin/pip install -r /srv/files/app/requirements.txt
sudo install -m 644 habang.service /etc/systemd/system/habang.service
sudo systemctl daemon-reload
sudo systemctl enable --now habang
```

`habang.service`는 localhost:8080에서 실행합니다. Nginx 또는 HTTPS 터널에서
이 포트로 프록시합니다. 서비스 설정의 `User`, `Group`, 경로는 설치에 맞춰 조정합니다.
전체 저장소를 정적 웹 서버의 공개 디렉터리로 서비스하지 마세요.
앱의 정적 파일 경로는 명시적으로 허용된 웹 파일만 제공합니다.

로컬 시험은 `SECRET_KEY`와 `BASE_URL=http://127.0.0.1:8080`을 설정한 뒤
`python app.py`로 실행합니다. 프록시 뒤에서도 요청 Origin은 BASE_URL과 같아야 합니다.
`TRUST_PROXY=1`이면 loopback에서 접속하는 프록시의 X-Forwarded-For 마지막 주소를
방문자 IP로 사용합니다. Nginx/Tailscale Serve/Cloudflare Tunnel처럼 실제 방문자 IP를
기록하는 로컬 프록시에서만 사용하고, 앱은 계속 localhost에 바인딩합니다.
다른 주소에서 직접 연결한 요청의 전달 헤더는 신뢰하지 않습니다.

## Google / GitHub OAuth 앱 등록

OAuth API는 사이트 운영자 계정으로 등록한 Client ID와 Client Secret이 필요합니다.
값이 비어 있는 제공자는 UI에서 준비 중으로 표시되며 이메일 회원가입은 사용할 수 있습니다.

Google Cloud Console의 Google Auth Platform에서 외부 사용자를 위한 앱과 웹 애플리케이션
클라이언트를 만듭니다. 범위는 `openid email profile`입니다.
승인된 리디렉션 URI에 **공개 BASE_URL + `/auth/google/callback`** 을 등록합니다.
시험 모드라면 허용할 테스트 사용자를 추가하고, 공개할 때 게시 상태를 확인합니다.

GitHub Settings → Developer settings → OAuth Apps → New OAuth App에서
Homepage URL은 BASE_URL, Authorization callback URL은
**BASE_URL + `/auth/github/callback`** 으로 등록합니다.
필요 범위는 `read:user user:email`이며 저장소 접근 권한은 요청하지 않습니다.

발급한 값은 서버의 `community.env`에 다음 이름으로 넣고 서비스를 재시작합니다.

```text
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET
```

이메일 계정과 소셜 계정은 이메일이 같아도 자동으로 합치지 않습니다.
소셜 로그인은 제공자별 고유 사용자 ID로 식별하고 Authlib의 OAuth state, PKCE,
Google ID 토큰 서명·issuer·audience·nonce 검증을 사용합니다.
자체 가입 이메일의 소유권 확인 및 비밀번호 재설정 메일 기능은 현재 포함하지 않습니다.

참고: [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect),
[GitHub OAuth 웹 흐름](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps).

## 운영 · 검증

회원 비밀번호는 Argon2id 해시로 저장하고 로그인 세션은 서버 DB에서 폐기할 수 있습니다.
세션 쿠키는 HttpOnly, SameSite=Lax이며 HTTPS에서는 Secure 및 `__Host-` 접두사를 사용합니다.
쓰기 API는 Origin과 CSRF 토큰을 검사하고, 로그인·회원가입·댓글 작성에 DB 기반 속도 제한을 적용합니다.
댓글 HTML은 실행하지 않고 텍스트로 표시합니다. 이메일은 댓글 API에 노출하지 않습니다.
`ADMIN_USER_IDS`에 지정한 사용자는 다른 회원의 댓글을 삭제할 수 있습니다.
관리자 ID는 `users` 테이블의 `id`를 확인해 설정합니다.

```sh
cd server
python -m unittest -v test_app.py
curl http://127.0.0.1:8080/api/health
sudo journalctl -u habang -n 50 --no-pager
```

실제 소셜 로그인 성공 검증에는 운영자 OAuth 설정과 사용자의 동의가 필요합니다.
테스트는 회원가입·로그인·세션 회전/폐기, CSRF, 페이지 분리·지속 저장,
작성자 권한, 파일 접근 차단, 입력 검증, 속도 제한, OAuth state/PKCE를 확인합니다.

SQLite 실행 중 DB 파일만 복사하면 WAL의 최신 기록을 놓칠 수 있습니다.
Python `sqlite3.Connection.backup()`으로 백업하고 복구한 DB로 확인하세요.
백업은 서버 밖에도 보관합니다.

## 공개 도메인과 Cloudflare Tunnel

Cloudflare에 기존 도메인을 추가하고 DNS 레코드를 가져온 뒤, 등록기관에서 지정된
네임서버로 전환합니다. Tunnel의 공개 애플리케이션 경로는 서비스
`http://127.0.0.1:8080`으로 연결합니다. 도메인 등록기관 이전은 필요하지 않습니다.

서버의 `/srv/files/bin/cloudflared`와 `cloudflared.service.example`을 사용할 수 있습니다.
터널 토큰은 `/srv/files/config/cloudflared.token`에 저장하고 권한을 600으로 지정합니다.
토큰을 Git에 올리거나 실행 명령어 인자에 직접 넣지 않습니다.
공개 경로를 적용하기 전에 `BASE_URL`과 Google/GitHub의 콜백 주소를 공개 도메인으로
함께 변경해야 합니다. 현재 운영 주소의 DNS 레코드를 먼저 확인하고 전환하세요.
`ALIAS_HOSTS=www.habang222.pro,habang.taila77bea.ts.net`처럼 이전 주소와 www 주소를
등록하면 GET/HEAD 요청은 BASE_URL의 같은 경로로 이동합니다. 별칭 주소에서는
쓰기 요청을 허용하지 않으므로 로그인·댓글은 기본 주소에서 진행합니다.
