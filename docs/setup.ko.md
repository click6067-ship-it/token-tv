# TokenTV 설정·참고 (한국어)

예전 README.ko.md의 전체 내용입니다. 사람과 AI 에이전트 모두를 위한 문서이고, [AGENTS.md](../AGENTS.md)도 함께 봅니다.

# TokenTV

[English README](../README.md) · [▶ 라이브 데모](https://token-tv.vercel.app)

![실제 시계에 띄운 Digital, Pixel Retro, Sci-Fi HUD 화면](images/real-clock.jpg)

**AI 사용 한도를 작은 책상 시계에.** Claude와 Codex 사용량을 여러 계정으로, 시계 펌웨어를 바꾸지 않고 보여줍니다.
Grok은 CLI 예산 정보를 보여주는 실험적 기능입니다. 제작자의 시계 구매 영수증은 5,650원(한국 알리익스프레스 할인가)이며 가격은 지역마다 다릅니다. 다른 기기는 확인하지 않았습니다. 켜 두는 컴퓨터(호스트)가 필요합니다.

240×240 책상 시계와 브라우저에서 확인하며, 계정별 인증 홈을 분리하고 실제 조회 실패와 오래된 값을 표시합니다.

## 실행

Python 3.10+와 사용할 공급자의 공식 CLI(`claude`, `codex`, `grok`)가 필요합니다.

```bash
pipx install git+https://github.com/click6067-ship-it/token-tv
token-tv demo     # 로그인 없이 샘플 데이터로 모든 시계 화면을 렌더
token-tv setup         # 공급자당 최대 3계정 이메일과 시계 IP만 묻고, 기존 설정은 덮어쓰지 않음
token-tv doctor --live # 지금 각 공급자에 조회해 빠진 CLI·로그인과 해결 명령을 안내
token-tv run      # 대시보드 http://127.0.0.1:8787 + 시계 전송
```

설정 파일은 `~/.config/token-tv/config.json`이며 모든 명령이 `--config`를 받습니다.
A 계정은 평소 쓰던 로그인(`~/.claude` 등)을 재사용할 수 있고, B·C 계정은
`~/.config/token-tv/homes/` 아래 별도 로그인 폴더를 씁니다. `token-tv connect --account codex_b`로
별도 계정에 로그인하며, 평소 로그인 위에 다시 로그인하려면 REPLACE를 입력해야 합니다.
`doctor`는 로그인 파일 존재만 보고, `doctor --live`는 실제 조회(만료 시 CLI 갱신 가능)를 하되
계정별 상태만 출력합니다. 기여 방법은 [CONTRIBUTING.md](../CONTRIBUTING.md)와
[시계 화면 만들기](clock-faces.md)를 봅니다.
아직 PyPI에 올리지 않았으므로 `uvx token-tv`는 동작하지 않습니다. 설치 없이 실행하려면
`uvx --from git+https://github.com/click6067-ship-it/token-tv token-tv demo`를 씁니다.
클론에서는 `pip install .`로 같은 명령을 설치합니다.

macOS(실기기 미검증): Claude Code가 로그인을 Keychain에 두므로, CLI 홈에
`.credentials.json`이 없으면 `security`로 읽기 전용 조회합니다. 이메일 대조는 그대로 합니다.

브라우저: `http://127.0.0.1:8787/`. `/snapshot`과 `/snapshot/<key>`는 JSON,
`/frame/0.jpg`는 시계와 같은 240×240 JPEG이며 `/frame/1.jpg`는 호환 별칭입니다.
시계는 Claude·Codex·Grok 각각 한 계정을 세 행으로 보여줍니다. 픽셀 아이콘, 큰 사용률 숫자, 막대, 기간 및 리셋 시간을 표시합니다.
실제 사용량을 제공하는 첫 계정을 선택하며 계정 전환은 수행하지 않습니다. Claude/Codex는 가장 높은 기간 사용률을 표시합니다.
영문 계정명은 `CLAUDE A/B/C`, `CODEX A/B`, `GROK A/B`로 구분합니다. 일곱 계정의 전체 기간과 조회 시각·오류 상태는 웹에서 공급자별로 확인합니다.
기본 조회 주기는 5분이며 브라우저를 열어도 추가 조회하지 않습니다.

### 화면 스타일

웹의 **Clock display**에서 시계 화면 6종을 미리 보고 고릅니다.
**Digital / Neon / Pixel Retro / Sci-Fi HUD**는 같은 이름의 웹 테마와 같은 글꼴·장식·게이지를
쓰고, 원래의 **Pixel**도 남아 있습니다. **Space**는 세 봇이 유리 헬멧을 쓰고 밤하늘을
떠다니는 움직이는 화면(GIF)이며, 사용률이 바뀌거나 30분이 지나면 새로 보냅니다. **Apply to clock**을 누르면 선택을 저장하고 같은 계정
캐시로 기기에 전송합니다. 미리보기만 선택하면 시계에는 적용되지 않습니다.

| Theme | 240×240 화면 표현 |
|---|---|
| Digital | 녹색 형광 터미널, 7세그먼트 숫자(꺼진 칸 표시), 호박색 리셋 시간 |
| Neon | 발광 카드 테두리, 아이콘 웰, 흰 숫자와 공급자 색 번짐, 둥근 칸 게이지 |
| Pixel Retro | 픽셀 프레임, 공급자별 픽셀 풍경, 마스코트, HP 블록 게이지 |
| Sci-Fi HUD | 모서리를 깎은 발광 프레임, 기울어진 칸 게이지 |

기존 Pixel(5×7 비트맵 글꼴과 픽셀 마스코트)도 같은 목록에서 고를 수 있습니다.
각 스타일은 Claude·Codex·Grok 한 계정과 10% 단위 10칸 게이지를 표시합니다.
설정의 `display_style`은 `digital`, `neon`, `retro`, `hud`, `pixel`, `space`를 지원하며 재시작 후에도 유지됩니다. 미설정 기본값은 `pixel`입니다.
숫자는 테마 내 공통 중성색입니다.
로고 색은 공급자별로 유지하며 게이지는 0–49% / 50–79% / 80–89% / 90–100% 구간마다 같은 색 계열의 두 색 그라데이션으로 표시합니다.
색만으로 상태를 전달하지 않으며 실제 숫자, 칸 수, 미인증/오래된 값 표기를 함께 제공합니다.

![시계 화면 6종의 실제 240×240 이미지(예시 데이터)](images/clock-faces.png)

새 화면은 참고 이미지를 바탕으로 코드로 그렸습니다. 원본 이미지의 가상 통계나 정적인 숫자는 포함하지 않습니다.
이미지를 자동으로 테마로 바꾸는 기능이나 테마 편집기는 현재 구현돼 있지 않습니다.

## 인증과 사용률

설정에는 계정 별칭, 예상 이메일, 공급자, 공식 CLI의 인증 홈 경로만 넣습니다.
비밀번호·API 키·OAuth 토큰 값을 설정에 넣으면 안 됩니다.
기기로 전송되는 내용은 사용률과 별칭을 그린 JPEG뿐입니다.

| 공급자 | 조회 경로 | 수치의 의미 |
|---|---|---|
| Claude | CLI 소유 OAuth의 profile/usage | 5시간 및 주간 **사용한 비율** |
| Codex | 공식 `codex app-server`의 계정/한도 RPC | 응답이 지정한 실제 기간의 **사용한 비율** |
| Grok | 공식 CLI billing RPC, 실험 단계 | 제공된 CLI **비용 한도**. 웹 대화 횟수와 별개 |

Claude/Codex는 예상 이메일과 인증된 이메일을 대조합니다.
Grok은 공식 CLI 인증 홈에 저장된 단일 계정 이메일도 대조합니다.
계정이 여러 개 섞인 인증 홈은 거부하며 billing 인증만으로 이메일을 추정하지 않습니다.
Grok이 한도 수치를 제공하지 않으면 `quota_unavailable`로 표시합니다.
`auth_required`, `identity_mismatch`, `rate_limited`, `error`, `stale`을 구별하며
이전 성공 값에는 `last_success_at`을 붙입니다. 실패한 값을 0%로 바꾸지 않습니다.

`refresh_with_cli: true`인 Claude 계정은 401일 때 공식 CLI로 인증 갱신을 시도합니다.
이 과정은 도구를 끈 짧은 확인 응답 하나를 요청하므로 구독 사용량을 소량 소비할 수 있습니다.
인증 파일의 토큰을 직접 수정하거나 다른 머신으로 복사하지 않습니다.

**5시간과 주간 중 무엇을 보여 주나요?** 둘 다 읽습니다. 시계는 사용률이 더 높은 쪽과 그 창의 리셋 시간을
보여 줍니다. 웹 대시보드도 같은 창을 먼저 보여 주고, 그 아래 다른 창 항목을 펼치면 나머지를 볼 수 있습니다.

**다른 화면(HYTE, Apple Watch)도 되나요?** 브라우저 대시보드는 있지만,
HYTE Y70 화면에서의 레이아웃은 시험하지 않았습니다. Apple Watch 앱은 현재 없습니다.

## 내 디자인 만들기

**동작하는 화면에서 시작하세요.** 시계·로그인·포크 없이 [Game Boy 예제](../examples/gameboy)를 실행하고
AI에게 바꿔 달라고 하면 됩니다. 시계 화면은 240×240을 그리는 Python 함수 하나이며,
[docs/clock-faces.md](clock-faces.md)를 따라 샘플 데이터로 만들 수 있습니다. 예제를 복사하거나 포크하는 것만으로는 등록되지 않습니다. 가이드대로 `RENDERERS`와 `STYLES`에 등록하면
대시보드 **Themes** 목록에 *Local*로 나타나 시계에 적용할 수 있습니다. 수정본은 로컬에 보관해도 되고,
GitHub에 보관하고 싶으면 포크하세요.

다른 사람과 나누려면 *New clock face* 템플릿으로 PR을 보내 주세요. 공유된 화면은 다음 릴리스부터
**Themes**에서 **Popular**(테마별 GitHub 이슈의 👍) 또는 **New** 순으로 보입니다. 좋아요는 릴리스 전에
수동으로 집계하며, 목록에 집계 시각이 표시됩니다.

## 시계 연결

확인된 경로는 SD_PRO 웹 UI의 `/theme/list`, `/photo/list`, `/photo/upload`입니다.
설정에 `"device_url": "http://<clock-ip>"`를 추가하면 사진 테마를 사용합니다.
기기 펌웨어를 바꾸지 않습니다. 기존 사진 파일은 보존하고 선택 상태만 변경합니다.
원래 테마와 사진 선택 상태는 설정 폴더의 `state/display-original.json`에 저장됩니다.

복원 전 데몬을 정지한 뒤 실행합니다.

```bash
token-tv run --restore-display
```

사진 API가 없는 다른 펌웨어는 아직 실기기로 검증하지 않았습니다. 확인된 범위와 내 시계 확인 방법은 [docs/hardware-compatibility.md](hardware-compatibility.md)에 있습니다.

## 다른 머신의 기존 인증 사용

Mini에 인증이 아직 없으면 `token_tv.bridge`로 노트북에서 검증한 정규화 JSON만
SSH로 보낼 수 있습니다. 설정의 `snapshot_file`이 해당 파일을 가리키도록 합니다.
그 계정은 화면에 노트북 연동으로 표시되며 15분 이상 갱신되지 않으면 오래된 값이 됩니다.
이 구성은 노트북이 켜져 있어야 동작합니다.

Mini 설정에 `source_home`과 `fallback_snapshot_file`을 함께 지정하면 Mini 로그인을
우선 사용하고, 인증이 없을 때만 노트북 조회로 대체합니다. 이메일 불일치는 대체로 숨기지 않습니다.
Mini의 해당 계정에 로그인하면 다음 5분 조회부터 노트북 의존성이 없어집니다.

```bash
# Mini의 프로젝트 디렉터리에서 계정을 선택합니다.
token-tv connect
```

인증번호는 로그인 터미널 또는 공식 브라우저 화면에 입력합니다. 제품의 HTTP API는
비밀번호나 인증번호를 받지 않습니다. 기본 CLI 홈과 Orca의 선택 계정은 바꾸지 않습니다.

```bash
python3 -m token_tv.bridge --config .runtime/laptop-config.json \
  --ssh-host mini --remote-path '~/path/to/token-tv/.runtime/laptop-snapshot.json'
```

## 검증과 기존 mock

```bash
python3 -B -m unittest discover -s tests -v
python3 -m token_tv.app
```

기존 mock 서버는 예시 데이터를 `status: "mock"`으로 제공하며 실제 사용량과 구별됩니다.

### Four web appearances

The live web dashboard provides **Digital Terminal, Neon Cyberpunk, Pixel Retro and
Sci-Fi HUD**. Choose an appearance above the
three provider cards. It is saved in this browser and does not change the physical
clock. Account buttons A/B/C switch each provider independently; expand **more
quota windows** to inspect the other reported limits. The large number always
names its selected quota period.

**Clock display** opens the 240×240 preview and five LCD styles. Previewing
is read-only; **Apply to clock** explicitly sends the chosen LCD style. Unknown
quota is shown as a dash, old readings carry an OLD label, and disconnected web
sessions retain their last readings with an offline notice. Grok CLI budget is
not the Grok web conversation quota.

Web files live in `token_tv/web/`; `token_tv/web/tokens.css` defines appearance colors and fonts.
`token_tv/web_assets.py` allowlists public files. The bundled fonts (Manrope, Orbitron,
Oxanium, Press Start 2P, Jersey 10, VT323, DSEG7 Classic, Chakra Petch) are served locally with their SIL Open Font License notices; the dashboard makes
no external font requests, and the clock renderer reuses the same files.

For a Mini Codex account whose device-code login is unavailable, use the normal
browser flow with `python3 -m token_tv.connect --config <private-config> --account
<key> --browser`, forwarding localhost port 1455 to the Mini during authentication.
This keeps each account's CLI home separate.

Browser regression checks use local Playwright Chromium:

```sh
PLAYWRIGHT_PACKAGE=/path/to/playwright-package \
CHROMIUM_EXECUTABLE=/path/to/chromium \
TOKEN_TV_TEST_URL=http://127.0.0.1:18787 \
node scripts/test_web_browser.cjs
```

The test captures four desktop/mobile appearances, tests five viewport widths,
account choices, missing/stale/offline data, and clock controls. Its apply request
is intercepted, so running it does not change a connected clock.

