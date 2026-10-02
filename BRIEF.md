# TokenTV — $5 AliExpress 시계를 AI 사용량 물리 대시보드로

## 목표 (왜)
GitHub 스타/레딧 바이럴이 목적. 훅은 "6천원짜리 알리 날씨시계가 Claude/Codex 사용량을 보여준다".
사용자는 이미 기기를 갖고 있고 (`~/ghq/.../token-tv`가 작업 디렉터리), 과거에 한 번 비슷한 걸 만들어봤음
(smalltv-mod 포크 + ai-usage-taskbar-widget에서 쿼터 받아 푸시) — 다만 디자인(AI생성 이미지 기반)이 별로였음.

## 하드웨어 현황 (중요: 아직 준비 안 됨)
- GeekMagic SmallTV 계열 시계, 현재 Mini PC에 USB로 전원만 연결된 상태.
- 아직 어떤 WiFi에도 붙어있지 않음 (사용자가 폰으로 핫스팟→집 WiFi 전환 작업을 곧 할 예정).
- **지금 단계에서는 기기 IP/실물 테스트가 불가능** — 그 전까지 할 수 있는 소프트웨어 작업만 먼저 진행.
- 기기가 WiFi에 붙으면 사용자가 IP를 알려줄 것 — 그 전까지는 이 작업을 TODO로 남겨두고 블로킹하지 말 것.

## 참고 레포 (반드시 먼저 clone해서 실제 코드 읽고 시작할 것 — 추측으로 짜지 말 것)
1. https://github.com/giovi321/smalltv-mod — 펌웨어 베이스 (ESP8266/SmallTV-ultra/ESP32-C2/ESP32 지원,
   WiFi OTA 지원, Claude usage meter 모드 이미 있음). 이 레포의 구조·OTA 업데이트 절차·기존 Claude 모드
   코드를 먼저 읽고, 거기에 얹는 방식으로 접근.
2. https://github.com/sallyHADEV/ai-usage-taskbar-widget — 멀티계정 인증 + 사용량 조회 로직 참고용.
   여기서 Claude/Codex 등 provider별 사용량을 어떻게 긁어오는지 확인하고 재사용 가능한 부분 파악.

## 아키텍처 (이전 기획 논의에서 정리된 방향)
```
PC(Mini) 데몬 ─(provider adapter: claude/codex/...)→ normalized JSON ─(LAN, HTTP)→ SmallTV(펌웨어)
```
- API 키/세션 토큰은 기기(ESP)에 절대 넣지 않는다 — Mini의 데몬에만 둔다.
- 데몬은 provider별로 플러그인 구조 (`providers/claude.ts`, `providers/codex.ts` 등 — 언어는 기존 참고
  레포들과 맞춰서 판단, 억지로 TS 고집할 필요 없음).
- 기기 쪽은 "dumb display"로 유지 — 가능하면 smalltv-mod의 기존 OTA/웹UI 인터페이스를 그대로 활용하고
  새 커스텀 펌웨어 빌드를 최소화 (논의에서 나온 "무플래싱에 가까운" 방향과, 사용자가 이미 자체 포크로
  진행한 "펌웨어 뜯어고침" 방향 중, smalltv-mod 코드를 실제로 읽어본 뒤 더 간단한 쪽으로 판단해도 됨 —
  단, 이 판단 근거를 나중에 설명할 수 있게 남겨둘 것).
- 다계정 지원 필수 (예: Claude personal/work 등 alias로 구분해서 화면에 표시).

## 지금 할 일 (기기 연결 전에 가능한 범위)
1. `smalltv-mod`, `ai-usage-taskbar-widget` 를 `vendor/` 또는 `reference/` 하위에 clone해서 코드 구조 파악
   (이 디렉터리는 git submodule이 아니라 그냥 참고용 — .gitignore 처리하거나 별도 clone 경로 사용).
2. 두 레포를 분석한 결과를 바탕으로, 이 프로젝트의 구체적 구현 계획(데몬 언어/구조, 펌웨어에 얹을 방식,
   provider 플러그인 인터페이스)을 `PLAN.md`로 작성. 추측 금지 — 읽은 코드 기반으로만 작성.
3. Mini 데몬 쪽 스캐폴딩(디렉터리 구조, provider interface, mock JSON 응답)까지는 기기 없이도 구현/테스트 가능 —
   거기까지 진행.
4. 기기 플래싱/실제 통신이 필요한 부분은 명확히 TODO로 표시하고 멈출 것 — 기기 IP를 받기 전까지는
   추측으로 "이 IP일 것이다" 하고 진행하지 말 것.

## 하지 말 것
- 존재하지 않는 API/엔드포인트를 추측해서 구현하지 말 것 — 반드시 clone한 레포의 실제 코드를 읽고 확인.
- 기기에 API 키/크리덴셜 저장하는 구조로 설계하지 말 것.
- 커밋/푸시는 아직 하지 말 것 (로컬 작업만, 사용자 확인 후 리모트 결정).

## 보고
작업 끝나면 무엇을 clone했는지, PLAN.md에 뭘 썼는지, 스캐폴딩 범위, 남은 블로커(기기 연결 대기 등)를
간결하게 정리해서 알려줘.
