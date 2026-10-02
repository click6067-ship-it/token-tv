# TokenTV 구현 계획

## 근거와 현재 결정

참고 코드는 `vendor/`에 별도 clone했고 Git 추적에서 제외했다.

| 저장소 | 확인한 코드 | 결론 |
| --- | --- | --- |
| `giovi321/smalltv-mod` @ `32d4832` | `src/features/usage/UsageClient.cpp:30`, `src/WebPortal.cpp:370`, `src/features/theme/ThemeDataClient.cpp:91`, `docs/src/content/docs/features/themes.md:163` | 기본 Claude 모드는 `{s,sr,w,wr,st,ok}`의 **단일** 사용량만 처리한다. `/api/usage` POST도 같은 단일 형식이다. 다계정은 테마의 JSON 데이터 바인딩으로 구현한다. |
| `giovi321/smalltv-mod` @ `32d4832` | `docs/src/content/docs/getting-started/flashing.md:14`, `src/WebPortal.cpp:513` | 설치 방법은 보드에 따라 다르다. ESP8266 일부와 Pro는 stock 웹 OTA가 가능하지만 ESP32-C2는 초기 설치에 USB 직렬 플래시가 필요하다. 현재 보드 미확인. |
| `sallyHADEV/ai-usage-taskbar-widget` @ `ac348ab` | `src/services/claude-local-client.ts:14`, `src/services/codex-app-server-client.ts:273`, `src/services/account-store.ts:32`, `src/services/usage-push.ts:4` | Claude는 로컬 CLI 세션 파일과 usage 조회를, Codex는 app-server의 `account/read`와 `account/rateLimits/read`를 사용한다. 위젯의 계정 목록은 있으나 Claude 로컬 소스가 전역 자격 증명을 공유하므로 personal/work의 독립 사용량을 이 코드만으로 보장하지 못한다. 위젯의 push 형식(`screen`, `items`)도 smalltv-mod의 `/api/usage` 형식과 호환되지 않는다. |

따라서 첫 화면 구현은 **smalltv-mod 정규 이미지 + `.stheme` 사용자 테마 + Mini HTTP 데몬**으로 한다. 테마는 펌웨어 재빌드 없이 URL에서 JSON 필드를 읽는다. Claude 기본 모드는 단일 계정 대안으로만 남긴다. 모델 확인 전에는 이미지와 설치 절차를 확정하지 않는다.

## 데이터 흐름

1. Mini 데몬에 `key`, `alias`, `provider`, 추후 `source`를 가진 계정을 등록한다. `key`는 테마 URL에 쓰는 안정적인 영숫자 ID이고 `alias`는 화면 표기명이다. 서로 다른 계정은 서로 다른 인증 소스를 가져야 한다.
2. provider adapter `fetch(account) -> Usage`가 세션/주간 사용률, 리셋까지 남은 분, 상태를 반환한다. 값이 없으면 `null`로 표현한다. 실패를 0% 사용으로 위장하지 않는다.
3. `GET /snapshot/<key>`는 한 계정의 작은 JSON을 제공한다. 테마는 계정당 data source 하나를 두고 `alias`, `status`, `session_percent`, `weekly_percent` 등의 scalar path를 바인딩한다. 전체 목록 `GET /snapshot`은 로컬 점검용이다.
4. smalltv-mod 테마의 제한은 source 최대 4개, source당 field 최대 8개, 응답 최대 2 KiB, 최소 갱신 간격 10초다 (`docs/src/content/docs/features/themes.md:163`). 그러므로 첫 테마는 최대 4개 계정을 한 화면에 고정 배치한다. 초과 계정의 페이지 전환은 후속 설계가 필요하다.

현재 스캐폴드는 Python 3 표준 라이브러리로 작성했다. Mini에서 의존성 없이 실행 가능하고, HTTP 서버와 provider 인터페이스를 빠르게 검증할 수 있다. 위젯의 Electron/Windows 전용 코드를 그대로 가져오지 않는다. 실데이터 adapter는 소스별 동작과 현재 인증 방식 확인 후 별도 구현한다.

## 단계

1. **지금: 완료** — 데몬 모듈, `Provider` 인터페이스, 구별되는 3개 mock 계정, `/snapshot` 및 `/snapshot/<key>` JSON 응답, 로컬 테스트. mock 값은 `status: "mock"`으로 명시한다. 인증 정보는 응답에 없다. 기본 바인드는 `127.0.0.1`이다.
2. **Mini 실데이터** — Claude/Codex adapter를 추가한다. 소스별 계정 구분 방법부터 검증한다. 다른 OS 계정/별도 세션 경로 등이 필요할 수 있으나 지금은 미검증이다. 실제 인증 파일의 원문을 로그/응답/저장소에 싣지 않는다. provider 조회 실패와 오래된 데이터를 `error`/`stale`로 노출하고 갱신 시각을 보존한다. 현재 API 동작은 구현 시 재확인한다.
3. **화면** — `smalltv-mod`의 `examples/themes/live-status/theme.json` 형식을 토대로 240×240 테마를 만든다. 계정 alias를 문자로 표시하고 사용률을 수치와 막대로 함께 표시한다. `tools/smalltv_theme.py validate`와 오프라인 preview로 디자인을 확인한다. URL은 확인된 Mini LAN 주소로 구성한다.
4. **기기 연결 후 TODO** — WiFi 연결 및 IP 확보, 실제 MCU/모델 확인, stock 펌웨어 백업 가능 여부와 설치 경로 확인, 해당 모델에 맞는 정규 이미지 설치, 테마 업로드, 기기에서 Mini URL 접근과 JSON 렌더 실측. ESP32-C2라면 초기 설치는 OTA가 아니라 USB 직렬 플래시 경로다. 실제 IP와 모델을 받기 전에는 플래싱하지 않는다.

## 판정 기준

- mock 단계: 서로 다른 3개 alias가 서로 다른 키로 조회되고, JSON에 토큰/자격 증명이 없고, 응답이 2 KiB 이하다.
- 실데이터 단계: 같은 provider의 두 계정이 실제로 서로 다른 세션에서 조회됨을 확인한다. 검증 전에는 다계정 실사용 완료로 표시하지 않는다.
- 기기 단계: 실제 240×240 화면에 alias와 사용률이 구별되어 렌더되고, 실패/오래된 값이 정상값으로 오인되지 않는다.

## 미해결 사항

- 기기 IP, 정확한 보드와 현재 firmware, Mini에서 접근 가능한 LAN 주소가 아직 없다.
- 실계정별 Claude/Codex 인증 소스는 아직 검증하지 않았다. reference 위젯만으로는 다계정 독립 조회가 성립하지 않는다.
- 테마 JSON URL은 LAN HTTP다. 사용량 수치만 노출하며 Mini의 자격 증명은 서버 안에 둔다. LAN 공개 시 접근 제어 방식은 실제 네트워크 확인 후 결정한다.
