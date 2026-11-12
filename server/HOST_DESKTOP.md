# Kali 호스트 원격과 Kali 컨테이너

`host-desktop.html`은 이메일 확인·가입 완료 회원만 API를 이용할 수 있고,
대여 자동 승인과 별도의 호스트 승인을 사용한다. 회원은 SSH 공개키와 사이트
비밀번호와 다른 원격 전용 비밀번호를 등록한다. 원문은 저장하지 않고
OpenSSL SHA-512 crypt 해시만 DB와 Linux shadow에 둔다.

호스트는 xrdp + Xorg/Xfce의 별도 세션이다. `127.0.0.1:3389` TLS 리스너에
Tailscale SSH 키 터널로 접속한다. PC에서는 로컬 `13389`를 사용한다.
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
서버 관리자 외에도 사용할 사람은 관리자가 Tailscale 네트워크에 초대해야 한다.

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
