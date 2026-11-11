# Google·GitHub 로그인 공개 운영 점검

이 문서는 `habang222.pro`의 실제 로그인 구현과 외부 OAuth 콘솔에 입력할 공개 정보만 담는다. Client Secret, 접속 암호, 토큰은 기록하지 않는다.

## Google Cloud 인증 플랫폼

| 항목 | 입력값 또는 확인할 값 |
| --- | --- |
| 앱 이름 | `habang222` (사이트에 표시되는 이름과 일치) |
| 사용자 지원 이메일 | `victor6580a@gmail.com` |
| 개발자 연락처 | `victor6580a@gmail.com` |
| 애플리케이션 홈페이지 | `https://habang222.pro/` |
| 개인정보처리방침 | `https://habang222.pro/privacy.html` |
| 서비스 이용약관 | `https://habang222.pro/terms.html` |
| 승인된 도메인 | `habang222.pro` |
| 웹 애플리케이션 리디렉션 URI | `https://habang222.pro/auth/google/callback` |
| 웹 애플리케이션 JavaScript 원본 | 서버 측 OAuth만 사용하므로 필요하지 않으면 비워 둔다. 입력한다면 `https://habang222.pro`만 사용한다. |
| 대상 | 일반 방문자가 로그인할 수 있도록 `외부` 및 게시 상태 확인 |
| 데이터 액세스 | `openid`, `email`, `profile`만 사용. Gmail, Drive, Contacts 권한은 요청하지 않음 |

공개 설명 예시: “habang222는 프로그램 안내·회원 전용 다운로드·댓글·API 키 발급·서버 대여 신청을 제공합니다. Google 계정은 인증된 이메일 주소와 기본 프로필로 회원 신원을 확인하거나 기존 회원 계정에 연결하는 데만 사용합니다.”

1. Google Search Console에서 `habang222.pro` 소유권을 이 Google Cloud 프로젝트의 소유자 또는 편집자 계정으로 확인한다. DNS 확인 레코드나 메타 태그는 Google이 제시한 값을 그대로 사용한다. 검증값을 이 저장소에 임의로 만들거나 Client Secret과 혼동하지 않는다.
2. Google Cloud 콘솔 → Google 인증 플랫폼 → **브랜딩**에서 위 홈페이지·개인정보처리방침·이용약관·지원 이메일·승인된 도메인을 입력한다. 공개 페이지는 로그인 없이 열려야 한다.
3. **대상**에서 외부 사용자의 게시 상태를 확인하고, **클라이언트**에서 정확한 공개 콜백을 확인한다. 개발 중 사용한 Tailscale 주소가 공개 클라이언트에 남아 있다면 제거할지 검토한다.
4. **데이터 액세스**에서 필요한 기본 신원 범위만 확인한다. 새 민감 범위를 추가하면 심사 요건이 달라질 수 있다.
5. **인증 센터**의 진단을 확인한 후 **Verify Branding**을 제출한다. 변경은 Draft Branding에만 저장될 수 있으므로 승인 후 **Publish branding**까지 확인한다. 콘솔 심사 상태는 이 문서 작성 시 별도로 확인해야 한다.

기본 로그인 범위는 민감한 Google API 범위가 아니다. 공개 앱의 이름·로고·도메인과 개인정보처리방침을 사용자에게 보여 주려면 브랜드 인증이 필요할 수 있다. 신청 완료와 Google의 승인 완료는 다르다.

## GitHub OAuth App

| 항목 | 입력값 또는 확인할 값 |
| --- | --- |
| Application name | `habang222` |
| Homepage URL | `https://habang222.pro/` |
| Authorization callback URL | `https://habang222.pro/auth/github/callback` |
| 권한 | 사이트에서 실제 요청하는 `read:user`, `user:email` |

운영 `/auth/google`과 `/auth/github` 응답에서 두 공개 콜백과 요청 범위를 확인했다. 사용자는 각 제공자에서 확인된 이메일로 사이트 회원가입을 별도로 완료한다. 비밀 키는 서버 전용 설정에만 둔다.

## 확인할 공개 URL

- `https://habang222.pro/`: 서비스 설명과 개인정보처리방침·약관·지원 링크
- `https://habang222.pro/privacy.html`: Google 데이터의 접근·사용·저장·공유 방식, 삭제 요청 방법
- `https://habang222.pro/terms.html`: 서비스 조건
- `https://habang222.pro/support.html`: 문의·개인정보 요청 안내
- `https://habang222.pro/api/health`: 서버 건강검사

공식 참고: [Google 브랜드 인증](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification), [Google 개인정보처리방침 요건](https://support.google.com/cloud/answer/13806988), [Google OAuth 정책 준수](https://developers.google.com/identity/verification/authentication-policy-compliance).
