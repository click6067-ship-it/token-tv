# TokenTV 설정·참고 (한국어)

예전 README에 있던 내용을 모두 담았습니다. 사람과 AI 코딩 에이전트 모두를 위한 문서이고, [AGENTS.md](../AGENTS.md)도 함께 보세요.

## 빠른 시작

와이파이에 연결된 GeekMagic SmallTV(SD_PRO 또는 Ultra)와 계속 켜 두는 컴퓨터가 필요합니다. 그 컴퓨터에는
Claude Code(`claude`), Codex(`codex`), Grok(`grok`) 가운데 쓰는 서비스의 공식 CLI가 설치되고 로그인돼 있어야
합니다. 브라우저에서 claude.ai나 chatgpt.com에 로그인한 것만으로는 안 됩니다.
[Claude Code](https://code.claude.com/docs/ko/quickstart)나 Codex(`npm install -g @openai/codex`)를 설치해 같은
계정으로 로그인하세요. `npx`에는 [Node](https://nodejs.org/)만 있으면 됩니다. Python이 필요하면 런처가 알아서
받아 옵니다.

```bash
npx token-tv start          # 또는: uvx token-tv start
```

pipx를 쓴다면 `pipx install token-tv` 다음에 `pipx ensurepath`를 실행하고, 새 터미널을 열어 `token-tv start`를 실행합니다.

`start`는 로그인된 Claude·Codex·Grok CLI를 찾아 이메일마다 확인을 받고, 와이파이에서 시계를 찾고(못 찾으면
시계가 켜질 때 화면에 나오는 주소를 묻습니다), TokenTV를 컴퓨터와 함께 시작해 계속 돌릴지 물은 뒤(설정 파일을
처음 만들 때만) 대시보드 http://127.0.0.1:8787 을 엽니다.
명령줄에서 고를 수 있는 것: `--face pixel`(기본 `arcade`), `--only codex`(또는 `claude,codex`),
`--device-url 192.168.0.50`. [라이브 데모](https://token-tv.vercel.app)가 이 줄을 만들어 줍니다.
`npx token-tv autostart off`는 백그라운드에서 도는 TokenTV를 멈추고 컴퓨터와 함께 시작하지 않게 합니다(시작할
때와 같은 방식으로: `uvx token-tv ...` 또는 `token-tv ...`). `autostart on`으로 다시 설정합니다. Linux에서는
시스템이 허용하면 로그아웃한 뒤에도 백그라운드에서 계속 돌고, 허용하지 않으면 TokenTV가 그렇다고 알려 줍니다.
나중에 공유기가 시계 주소를 바꿔도 TokenTV가 알아서 다시 찾습니다. 시계 없이 설정했다면 시계를 와이파이에 연결한
뒤 `start`를 한 번 더 실행하면 그때 찾습니다(같은 와이파이의 시계가 남의 것일 수 있어 혼자서는 찾지 않습니다). `start --device-url 192.168.0.50`으로 언제든 직접 넣어도 됩니다.

Windows에서는 claude·codex가 로그인된 쪽(Windows 또는 WSL)에서 TokenTV를 실행하세요. Node를 설치한
Windows에서 바로 돌리는 게 가장 간단하고, WSL은 마지막 터미널을 닫으면 곧 꺼집니다. 컴퓨터가 잠자기 상태일
때는 시계가 마지막 그림을 그대로 보여 줍니다.

계정을 더 넣거나 직접 다루려면(아래는 `token-tv`로 적었습니다. `npx`나 `uvx`로 실행한다면 앞에 붙이세요):

```bash
token-tv demo                 # 로그인 없이 샘플 데이터로 모든 시계 화면
token-tv setup                # 이메일(공급자당 최대 3개)과 시계 IP를 물음
token-tv doctor --live        # 지금 각 공급자에 물어, 빠진 것과 고칠 방법을 알려 줌
token-tv run                  # 대시보드 http://127.0.0.1:8787, 시계 구동
```

클론에서는 `python3 -m venv .venv && .venv/bin/pip install .`로 같은 명령을 `.venv/bin/token-tv`로 쓸 수 있습니다.

**업데이트:** `npx token-tv update`(또는 `uvx token-tv update`)가 백그라운드로 도는 TokenTV를 최신 릴리스로 바꿔
다시 켭니다. 설정과 로그인은 그대로입니다. 새 릴리스가 나오면 대시보드에 작게 알려 줍니다(PyPI를 하루 한 번 확인,
설정에 `"update_check": false`면 끔). 새 화면과 지원 시계는 [릴리스](https://github.com/click6067-ship-it/token-tv/releases)로
나옵니다. 받아 보려면 Watch → Custom → Releases. 로그인 정보는 내 컴퓨터에만 있습니다: TokenTV는 각 서비스의 CLI가
저장한 로그인으로 사용량만 묻고, 시계는 그림만 받습니다.

<p align="center"><img src="images/usage-examples.png" alt="사용량이 적을 때, 바쁠 때, 한도에 가까울 때의 Digital 화면(샘플 데이터)"></p>

<details>
<summary><b>모든 시계 화면</b></summary>

<br>

![Digital, Neon, Pixel Retro, Sci-Fi HUD, Pixel, 움직이는 Space 화면(샘플 데이터)](images/clock-faces.png)

위에 여섯 가지가 있고, 그 밖에 **Game Boy**(초록 네 색), **Pixel Retro Dual**(Pixel Retro에 계정마다 5시간·주간
창을 함께 보여 줌, `retro-dual`), 움직이는 **Arcade**(아래)가 있습니다.
대시보드의 **Clock display**에서 하나를 고르고 **Apply to clock**을 누르세요. Space는 순정 사진 앨범이 재생하는
움직이는 GIF입니다. 그린 이미지가 직전에 보낸 것과 다를 때만 다시 보냅니다. 사용률이 바뀌었을 때나, 30분마다
바뀌는 Space 애니메이션이 그 예입니다.

계정마다 한 줄씩, 최대 네 줄입니다. 줄들이 화면을 나눠 쓰므로 계정이 하나면 화면을 다 채우고, 둘이면 반씩
씁니다. 넷이 넘으면 지금 쓰는 계정을 먼저, 그다음 가장 많이 쓴 계정을 남깁니다. 두 줄까지는 5시간 창과 주간
창을 둘 다, 세 줄이나 네 줄이면 주간 창을 보여 줍니다.

**Arcade**도 움직이는 화면이고, 캐릭터마다 그림이 곧 한도 하나의 게이지입니다(작게 5H, WK 등으로 표시).
Claude의 달은 5시간 한도의 남은 양이고, Codex 꽃밭에는 20% 쓸 때마다 괄호꽃이 한 송이씩 피고, 발사대 옆 Grok의
연료탱크는 쓸수록 줄고, Copilot의 하늘은 20%마다 구름이 하나씩 차고, Anti(Antigravity)의 파워 펠릿 네 개는
5시간 한도의 남은 양입니다. 최근 10분 안에 사용률이 오른 계정은 일하는 중입니다. Clawd는 이리저리 달리고(동작은
claude.dev의 Clawd's Quest에서 가져왔습니다), Codex 구름은 꽃밭에 0·1과 코드 기호 비를 뿌리고, Grok은 팰컨 헤비에
연료를 넣거나 콘솔에서 점검하고, Copilot은 구름 아래를 가로질러 날고, Anti는 미로를 순찰합니다. 쉴 때는 숨을
쉬다가 가끔 둘러보고 기지개를 켭니다. 90% 넘게 쓰면(85% 아래로 내려갈 때까지) 저마다 다르게 초조해하며 더 많이
움직입니다. 창이 리셋되면 폭죽이, 다 쓰면 털썩 쓰러지는 장면이 한 번 나옵니다. Codex의 저장된 한도 리셋은
머리줄에 금색 티켓과 남은 개수로, 만료 전 마지막 사흘 동안은 빨간 D-n으로 보입니다. 밤 11시부터 아침
6시까지는 화면이 어두워집니다. 더 드문 장면 몇 개는 숨겨져 있습니다. 잠긴 채로 들어 있다가 그 순간이 실제로
시계에 찾아올 때만 열리고(레어는 며칠에 한 번, 유니크는 한두 주에 한 번), 몇몇은 장면에 작은 기념품을 잠시
남깁니다. Arcade는 한 번에 한 계정을 보여 줍니다(일하는 계정들을 차례로, 모두 쉬고 있으면 전부를 차례로).
결제 데이터가 없는 Grok 로그인처럼 사용률을 알려 주지 않는 계정은 일하는 중으로 치지 않습니다.
</details>

## 내 화면 만들기

**동작하는 화면에서 시작하세요.** 시계·로그인·포크 없이 [Game Boy 예제](../examples/gameboy)를 실행하고
AI에게 바꿔 달라고 하면 됩니다. 시계 화면은 240×240 픽셀을 그리는 Python 함수 하나이고,
[docs/clock-faces.md](clock-faces.md)가 샘플 데이터로 차근차근 안내합니다.
예제를 복사하거나 포크하는 것만으로는 등록되지 않습니다. 가이드대로 `RENDERERS`와 `STYLES`에 넣으면 대시보드
**Gallery**에 *Local*로 나타납니다. 수정본은 로컬에 두어도 되고, GitHub에 두고 싶으면 포크하세요.

다른 사람도 쓰게 하고 싶다면 일반 PR을 열고
[New clock face 체크리스트](../.github/PULL_REQUEST_TEMPLATE/theme.md)를 복사해 넣으세요. 공유된 화면은 다음
릴리스부터 모든 사람의 **Gallery**에 나오고, **Popular**(테마별 GitHub 이슈의 👍) 또는 **New** 순으로 정렬됩니다.
좋아요는 릴리스 전에 손으로 세므로, 목록에 언제 셌는지가 나옵니다.

<details>
<summary><b>하드웨어</b></summary>

- 순정 펌웨어에 사진 앨범 페이지가 있는 GeekMagic **SmallTV** 240×240 Wi-Fi 시계: **SD_PRO**(제작자의 영수증은
  5,650원, 한국 알리익스프레스 할인가이며 가격은 지역마다 다릅니다) 또는 **SmallTV-Ultra**(기여자들이 확인).
  다른 기기는 확인하지 않았습니다.
- 같은 네트워크에서 계속 켜 두는 컴퓨터. 쓰는 공식 CLI가 로그인돼 있고, Node(또는 Python 3.11+)가 있어야
  합니다.

SD_PRO의 사진 API(`/theme/list`, `/photo/list`, `/photo/upload`)는 제작자의 시계에서 확인했습니다. 다른 펌웨어를
쓰는 복제품은 시험하지 않았습니다.
확인된 범위와 내 시계 확인 방법은 [docs/hardware-compatibility.md](hardware-compatibility.md)에 있습니다.
</details>

<details>
<summary><b>사용량을 읽는 방법</b></summary>

| 공급자 | 출처 | 숫자의 뜻 |
|---|---|---|
| Claude | Claude Code CLI 자체의 OAuth 로그인(profile, usage) | 5시간·주간 한도 중 **사용한** 비율 |
| Codex | 공식 `codex app-server`의 계정·한도 RPC | 보고된 창마다 **사용한** 비율 |
| Grok | Grok CLI billing RPC(실험 단계) | CLI **결제 예산** 중 쓴 비율, 웹 대화 한도가 아님 |

모든 로그인은 설정한 이메일과 대조합니다. 시계는 그림만 받고, 비밀번호·토큰·쿠키는 절대 받지 않습니다.
조회는 1분마다, Claude 계정은 5분마다 합니다. Claude의 사용량 엔드포인트가 잦은 호출을 제한하기 때문입니다.
오래된 값에는 OLD가 붙고 없는 값은 대시로 보이며, 가짜 0%로 바꾸지 않습니다. `refresh_with_cli: true`인
Claude 계정은 만료된 로그인을 CLI로 갱신할 수 있고, 이때 아주 짧은 프롬프트 하나를 보냅니다.

[CodexBar](https://github.com/steipete/CodexBar)를 이미 쓰나요? Claude나 Codex 계정은 대신 CodexBar의 사용량
JSON을 읽을 수 있습니다. [docs/codexbar.md](codexbar.md)를 보세요.

**5시간, 아니면 주간?** 두 창을 모두 읽습니다. 시계는 더 많이 쓴 쪽을 그 창의 리셋 시각과 함께 보여 줍니다.
웹 대시보드도 같은 창을 먼저 보여 주고, 그 아래 다른 창들을 펼치면 나머지를 볼 수 있습니다.

**다른 화면(HYTE, Apple Watch)은?** 브라우저 대시보드는 있지만, HYTE Y70 화면에서의 레이아웃은 시험하지
않았습니다. Apple Watch 앱은 없습니다.
</details>

<details>
<summary><b>계정, 시계, 복원</b></summary>

- `setup`에서 A 계정은 이미 있는 로그인(`~/.claude`, `~/.codex`, `~/.grok`)을 다시 쓸 수 있고, B·C 계정은
  `~/.config/token-tv/homes/` 아래에 각자의 로그인 폴더를 받습니다.
  묻지 않고 하려면 플래그를 반복합니다. 예: `token-tv setup --yes --codex-email a@x.com --codex-email b@x.com`.
  `--isolate`를 붙이면 A 계정도 자기 폴더를 받습니다.
- `token-tv add codex --email b@x.com`은 이미 있는 설정(`start`가 만든 것 등)에 같은 서비스의 계정을 하나
  더 넣고, 그 계정만의 로그인 폴더를 만들어 로그인시킵니다. 평소 쓰던 로그인은 그대로입니다. 그 뒤 TokenTV를
  다시 시작해야 새 계정을 읽습니다.
- `token-tv connect --account codex_b`는 별도 계정을 그 서비스의 공식 CLI로 로그인시킵니다. 평소 쓰는
  `~/.claude` / `~/.codex` 로그인 위에는 REPLACE를 입력하지 않는 한 다시 로그인하지 않습니다.
- `token-tv doctor`는 로그인 파일이 있는지만 봅니다. `doctor --live`는 대시보드와 같은 확인을 합니다. 각
  공급자에 사용량을 묻고, 만료된 로그인을 CLI가 갱신하게 할 수 있으며, 계정마다 상태만 출력하고 토큰은 절대
  출력하지 않습니다.
- 설정 파일은 `~/.config/token-tv/config.json`에 있습니다. `setup`은 이미 있는 설정을 덮어쓰지 않으며, 다른
  경로를 쓰려면 어느 명령에든 `--config`를 주면 됩니다.
- 설정에는 별칭, 이메일, CLI 홈 경로만 들어갑니다. 비밀번호, API 키, 토큰은 절대 넣지 마세요.
- 시계를 나중에 넣거나 바꾸려면 `token-tv start --device-url <clock-ip>`를 실행하세요. 주소를 설정의
  `device_url`에 저장하고, 이미 돌고 있는 TokenTV는 1분 안에 그 주소를 씁니다.
- 시계에 원래 사진과 테마를 돌려주려면 TokenTV를 멈추고 `token-tv run --restore-display`를 실행합니다.
- **macOS(실제 Mac에서는 시험하지 않음):** Claude Code는 로그인을 Keychain에 두므로, CLI 홈에
  `.credentials.json`이 없으면 TokenTV가 `security`로 읽기 전용 조회합니다. 로그인은 여전히 설정한 이메일과
  대조합니다. Codex와 Grok은 Linux와 같이 파일을 읽습니다.
</details>

<details>
<summary><b>현황과 기여</b></summary>

초기 단계이고 책상 하나를 위해 만들었습니다. 설정은 `token-tv start`와 CLI 로그인이고, Linux에서 제작자의
SD_PRO와 기여자들의 SmallTV-Ultra 시계로 시험했으며, Claude·Codex·Grok을 지원합니다. 새 공급자를 넣으려면
여러 파일을 고쳐야 합니다. [공급자 추가하기](adding-a-provider.md)를 보세요. 공급자, 시계 모델, 화면에 관한
이슈와 PR을 환영합니다. [CONTRIBUTING.md](../CONTRIBUTING.md)와 [시계 화면 만들기](clock-faces.md)를 보세요.
</details>

<details>
<summary><b>개발</b></summary>

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python scripts/render_usage_examples.py   # docs/images/usage-examples.png
.venv/bin/python scripts/render_clock_faces.py      # docs/images/clock-faces.png
.venv/bin/python scripts/build_demo.py --out site   # 정적 라이브 데모
```

`scripts/test_web_browser.cjs`는 로컬 Playwright Chromium으로 브라우저 검사를 돌립니다.
</details>

MIT, [LICENSE](../LICENSE)를 보세요. 함께 넣은 글꼴의 SIL Open Font License 고지는 `token_tv/web/`에 그대로
있습니다. · [English](setup.md)
