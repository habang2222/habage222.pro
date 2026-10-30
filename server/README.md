# 로그인 · 회원가입 · 페이지별 댓글

현재 추가 서비스는 `/services.html`, 관리자는 `/admin.html`에서 사용합니다.

## 프로그램별 다운로드 API 키

사이트의 `/downloads/<파일명>`은 로그인 회원의 세션을 확인합니다. 외부 프로그램은
`Authorization: Bearer ...` 헤더로 프로그램별 API를 호출합니다. 키는 발급 직후 한 번만
표시하며 DB에는 SHA-256 해시만 저장합니다. 한 키는 한 프로그램의 파일에만 접근하고,
7·30·90일 만료, 폐기, 마지막 사용·사용 횟수를 지원합니다. 활성 키는 회원당 5개입니다.

```sh
curl --fail --output package.zip \
  --header 'Authorization: Bearer YOUR_PROGRAM_KEY' \
  https://habang222.pro/api/v1/programs/lecture-alarm/download
```

`GET /api/v1/programs/<program>`은 파일명·크기·SHA-256을 반환하고,
`GET /api/v1/programs/<program>/files/<filename>`은 특정 파일을 전송합니다.
프로그램 ID는 `photo-sorter`, `mglogwh`, `lecture-alarm`, `random-backspace`입니다.
키당 API는 분당 60회, 실제 다운로드는 시간당 60회입니다. URL 쿼리의 키는 받지 않습니다.
Windows 설치 도우미도 프로그램 키를 안전 입력으로 받아 서버 API에서 후속 파일을 받습니다.

APK는 웹 디렉터리 밖의 `/srv/files/artifacts/PhotoSorter.apk`에서 제공합니다.
`fetch_artifacts.py`는 고정한 v1.2.0 릴리스와 SHA-256을 검사해 이 파일을 준비합니다.
다른 배포 파일은 기존 `site/downloads`에 있습니다. `download_catalog.py`의 명시적 허용
목록 외 파일은 제공하지 않습니다. GitHub의 기존 공개 원본을 비공개로 바꾸는 작업은 하지 않았습니다.

## 승인 후 자동 컨테이너 대여

미승인 회원은 신청 후 관리자의 개별 승인을 기다립니다. 자동 승인 계정은 신청 즉시
생성 대기열에 들어갑니다. 관리자가 계정을 승인하면 기존 대기 신청도 함께 생성합니다.
`ADMIN_USER_IDS`로 지정한 운영자만 승인·거절·계정 정책·전체 대여를 관리합니다.
API 키에는 관리자나 컨테이너 제어 권한이 없습니다.

별도 Linux 계정 `habang-rentals`가 rootless Podman 워커를 실행합니다. 웹 앱에는
Podman 소켓이나 root 권한을 주지 않습니다. 두 서비스가 DB를 공유하기 위해 `habang-data`
그룹과 데이터 디렉터리 2770, DB 660, UMask 0007을 사용합니다. OAuth 환경 파일은 계속 600입니다.

컨테이너는 0.5 CPU, 384MB RAM, swap 추가 사용 금지, PID 64개, 임시 홈 128MB,
임시 /tmp 32MB, 읽기 전용 루트, 축소한 capability, no-new-privileges로 실행합니다.
기간은 최초 정상 생성부터 24시간이며 회원당 1개, 전체 기본 2개입니다. 홈 파일은
중지·재시작 때 초기화되므로 지속 저장 VPS로 설명하지 않습니다. Python·Git·curl과 SSH/SFTP가
있고 접속 사용자는 `tenant`입니다. 개인키는 받지 않고 SSH 공개키만 받습니다.
SSH 호스트 키는 재시작 때 유지하며, 종료 시 제거합니다.

SSH는 Tailscale IP에만 23000~23019 범위에서 바인딩합니다. 방문자는 Tailscale에 연결되어
있어야 실제 SSH/SFTP에 접속할 수 있습니다. 웹 신청과 API는 일반 공개 HTTPS에서 동작합니다.
컨테이너는 호스트 커널을 공유하므로 별도 가상머신과 같은 격리로 설명하지 않습니다.

워커는 DB 작업을 임대 시간과 함께 원자적으로 가져오며, 컨테이너 이름·관리 label을
대조해 재처리 때 다른 컨테이너를 삭제하지 않습니다. 생성 실패는 `failed`로 표시하고,
가짜 접속 정보를 보여주지 않습니다. 만료 시 자동 종료하고, 시작·중지·재시작·종료를 지원합니다.
관리 작업은 `admin_events`, 다운로드는 `download_events`에 기록합니다.

```sh
sudo systemctl status habang habang-tunnel habang-rentals
sudo journalctl -u habang-rentals -n 80 --no-pager
```

rootless 실행 환경의 HOME, XDG_RUNTIME_DIR, DBUS_SESSION_BUS_ADDRESS, DATABASE,
RENTAL_IMAGE 등을 `rental-worker.env`에 설정합니다. `habang-rentals.service.example`을
참고하세요. 워커는 uid/gid 매핑을 위한 newuidmap/newgidmap이 필요하므로 워커 서비스에
NoNewPrivileges를 강제하지 않습니다. 컨테이너 안에는 no-new-privileges를 적용합니다.
앱 서비스는 기존 NoNewPrivileges 보호를 유지합니다.

검증은 `python -m unittest -q test_app.py test_portal.py`로 실행합니다. 실제 호스트에서는
별도 임시 DB·임시 SSH 키로 컨테이너 생성, 공개키 로그인, cgroup 자원 값, 임시 파일 초기화,
호스트 키 유지, 종료 후 제거를 검증했습니다. 운영 회원의 대여를 테스트용으로 만들지 않았습니다.

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
