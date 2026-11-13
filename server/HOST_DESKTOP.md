# Kali 호스트 원격과 Kali 컨테이너

`host-desktop.html`은 이메일 확인·가입 완료 회원만 API를 이용할 수 있고,
대여 자동 승인과 별도의 호스트 승인을 사용한다. 회원은 선택 사항인 SSH 공개키와 사이트
비밀번호와 다른 원격 전용 비밀번호를 등록한다. 원문은 저장하지 않고
OpenSSL SHA-512 crypt 해시만 DB와 Linux shadow에 둔다.

호스트는 xrdp + Xorg/Xfce의 별도 세션이다. 현재 기본 접속은 웹사이트 내부의
Guacamole 캔버스 화면이다. 인터넷이 되는 다른 네트워크에서도 이용할 수 있다.
고급 SSH 터널 접속만 Tailscale과 공개키를 사용한다.
회원 `hbdesk_*`는 별도 홈 700, 개인 기본 그룹과 `hbdesktop`만 갖는다.
SSH 셸·SFTP·다른 포트 포워딩은 허용하지 않는다. RDP 프록시 세션 유형과
PC 드라이브 리디렉션도 끈다. 실제 호스트 계정이므로 컨테이너 수준의
자원·네트워크 격리는 없고 신뢰하는 회원만 승인해야 한다.

## 설치와 검증

xrdp/xorgxrdp를 설치하기 전에 `systemctl mask xrdp xrdp-sesman`으로 자동 시작을
막고, 설치 후 root로 `configure-host-desktop.sh`를 실행한다. 스크립트는 기존
SSH/xrdp 설정 백업, 루프백·TLS 설정, 제한된 SSH Match 규칙을 검사하고 적용한다.
기존 관리자 키 접속과 3389 외 포워딩 차단을 별도 연결에서 확인한다.

root 워커는 **앱이 쓸 수 없는** `/usr/local/lib/habang-host-desktop`에
`host_desktop_worker.py`와 `rental_common.py`를 root:root 644로 설치한다.
`habang-host-desktop.service.example`을 systemd에 설치하고 DB에 새 스키마가
생긴 뒤 시작한다. 워커는 3초마다 승인과 인증 상태를 확인한다. 회수 시 SSH 키를
제거하고 계정을 만료·잠금 처리하며 세션을 종료한다. 사용자 홈은 삭제하지 않는다.
웹 접속 회원은 Tailscale 초대나 Windows 원격 데스크톱 프로그램이 필요하지 않다.

## 브라우저 원격 화면 (2026-11-13)

`host-desktop.html`의 내 Kali 작업 화면에서 원격 비밀번호를 입력한다. 관리자 계정은
기존 `habang222`, 승인 회원은 DB에서 파생한 본인의 `hbdesk_*` 계정만 사용한다.
홈페이지 계정과 OS 계정은 구분되며 다른 회원에게 관리자 계정을 공유하지 않는다.
신청 시 SSH 공개키를 비워 두면 authorized_keys도 비어 있어 웹 접속만 가능하다.

연결 경로는 브라우저 → `wss://habang222.pro/api/remote/host` → 기존 Cloudflare
Worker/Tunnel → Gunicorn/Flask-Sock → `127.0.0.1:4822` guacd →
`127.0.0.1:3389` xrdp(TLS)이다. 4822와 3389는 외부 인터페이스에 열지 않는다.
공개키/개인키를 웹사이트가 대신 보관하거나 사용자에게 별도 프로그램 실행을 요구하지 않는다.

게이트웨이는 WebSocket 업그레이드 전에 사이트 세션과 정확한 Origin을 확인하고,
첫 WSS 메시지의 CSRF 토큰과 전용 원격 비밀번호를 확인한다. 원격 비밀번호는 로그인
중 메모리에서만 전달하며 URL, DB, 로그, 프로세스 인수에 기록하지 않는다. 브라우저가
호스트·포트·Linux 사용자명·다른 연결 ID를 고를 수 없고, select/connect/file/clipboard
같은 입력 명령도 차단한다. 파일·클립보드·드라이브 리디렉션과 소리는 사용하지 않는다.
로그인 만료/로그아웃/이메일 인증 해제/호스트 승인 회수는 2초마다 재검사한다.

한 회원당 원격 연결 한 개, 전체 최대 네 개를 SQLite 임대로 제한한다. 임대는 2초마다
갱신하고 비정상 프로세스 종료 후 20초 안에 만료된다. 30분간 마우스/키보드 입력이
없거나 연결 후 2시간이 지나면 종료하며, 사용자는 다시 연결할 수 있다. 연결 종료와
OS 로그아웃은 다르다. OS 작업을 끝낼 때 Xfce 메뉴에서 로그아웃한다.

1280×720 기본 화면, 선택 가능한 해상도, 화면 맞춤, 전체 화면, 터치 마우스와
Ctrl+Alt+Del 버튼을 제공한다. 배경화면·테마·창 끌기 효과를 꺼 전송량을 줄인다.
인증/승인 패널은 갱신되어도 열린 작업 화면은 다시 만들지 않는다.

서버에는 `requirements.txt`의 Flask-Sock/simple-websocket을 설치한다.
`habang-guacd.service.example`을 root 소유 systemd 유닛으로 설치하고 시작한다.
guacd는 공식 `guacamole/guacd:1.6.0`의 고정 digest를 사용하고, 비루트 사용자로
읽기 전용 컨테이너·capability 제거·메모리 384MB/CPU 1/PID 128 제한에서 실행된다.
PID 파일만 `/tmp/guacd.pid`에 작성한다. 유닛의 `-l`은 포트, `-p`는 PID 파일이다.
사이트 서비스는 `configure-browser-remote.sh`로 워커당 8개 스레드를 할당한다.

정적 JS는 Apache 공식 guacamole-1.6.0.war에서 추출한 common-js이며 SHA-256
`b41ceb1e2df010b54db563e0b00edb8d5fe9f073c6168462e4c978df0fc6e716`을
공식 `.sha256` 파일과 대조했다. 출처와 Apache 라이선스는 `GUACAMOLE-LICENSE.txt`,
`GUACAMOLE-NOTICE.txt`에 보존했다. 백업 Pages의 remote-desktop.js는 오프라인
대체본으로 교체되어 원격 연결을 시도하지 않는다.

검증: `test_remote_desktop.py`는 세션/소유권/Origin/임대 경합/프로토콜 차단을 검사한다.
명시적 root `HOST_BROWSER_QA=1 python test_remote_desktop_live.py`는 운영 DB에
무작위 임시 QA 회원과 OS 계정을 만들고 공개 WSS를 통해 실제 Xfce 프레임·입력,
잘못된 Origin/CSRF 거절과 실시간 승인 회수를 확인한다. finally에서 테스트 계정·홈·
세션·승인·임대·감사 기록을 제거하며 실제 회원의 비밀번호나 승인은 변경하지 않는다.
운영 환경에서 실행하기 전 DB 백업을 만들고 다른 프로비저닝 코드를 동시에 실행하지 않는다.

`python -m unittest test_host_desktop.py test_host_desktop_worker.py`는 권한과
회수 경합을 검사한다. root에서 명시적으로 `HOST_DESKTOP_QA=1 python3
test_host_desktop_live.py`를 실행하면 임시 DB·키·계정으로 실제 Xfce 로그인,
SSH 제한, 회수를 확인하고 테스트 계정을 제거한다. 운영 회원 DB는 사용하지 않는다.

## Kali 컨테이너

`Containerfile.kali`는 공식 `kalilinux/kali-rolling`에 Openbox/noVNC를 설치한다.
기본 도구만 포함하며 Kali 보안 도구 메타패키지는 포함하지 않는다. 이미지가 CA
인증서 없이 시작하므로 서명 검증이 있는 Kali 미러를 bootstrap 단계에서 사용한다.
빌드는 `podman build --network=slirp4netns -t localhost/habang-kali-workspace:1
-f Containerfile.kali .`로 rootless 대여 계정에서 한다. 새 워커를 시작하기 전에
Debian·Kali 이미지가 모두 있어야 한다. 기존 Debian 대여는 유지된다.
Kali는 512MB, Debian은 384MB이며 다른 임시 공간·CPU·이용 시간 정책은 같다.
`RENTAL_QA_PLAN=kali-workspace RENTAL_QA_EXTERNAL=1`로 `verify_rental_runtime.py`를
실행하고, 출력된 임시 폴더를 root의 `probe_rental_external.py`에 넘기면 실제
SSH/noVNC·메모리 제한·포워딩 제한·종료를 확인한다. root 측 프로브를 사용하는
이유는 대여 UID의 사설망·Tailnet 접근 방화벽을 테스트 중에도 유지하기 위해서다.
