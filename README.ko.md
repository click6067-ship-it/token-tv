<h1 align="center">TokenTV</h1>
<p align="center">
  <a href="https://github.com/click6067-ship-it/token-tv/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/click6067-ship-it/token-tv"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <a href="https://hackaday.com/2026/10/06/smalltv-hacking-with-surprisingly-little-fuss/"><img alt="Featured on Hackaday" src="https://img.shields.io/badge/featured%20on-Hackaday-1a1a1a"></a>
  <a href="https://github.com/steipete/CodexBar#desk-display"><img alt="Listed in CodexBar" src="https://img.shields.io/badge/listed%20in-CodexBar-555555"></a>
</p>

<p align="center"><img src="docs/images/real-clock.jpg" alt="작은 책상 시계에 띄운 TokenTV"></p>
<p align="center"><img src="docs/images/arcade.gif" width="320" alt="움직이는 Arcade 화면(샘플 데이터): Clawd, Codex 구름, Grok, Copilot, Anti가 일하는 모습, 그림이 곧 게이지"></p>
<p align="center"><img src="docs/images/clock-faces.png" alt="시계 화면 몇 가지(샘플 데이터)"></p>

약 5달러 Wi-Fi 책상 시계에 Claude·Codex 사용 한도(그리고 Grok, CodexBar를 거쳐 Copilot·Antigravity)를 띄웁니다. 펌웨어는 그대로예요.  
**새 화면 Arcade:** 캐릭터마다 그림이 곧 게이지인 움직이는 화면입니다. 드문 장면 몇 개는 그 순간이 실제로 찾아올 때만 열립니다.  
**구경하기:** [라이브 데모](https://token-tv.vercel.app), `npx token-tv demo` 또는 `uvx token-tv demo`, 시계·로그인 없이 바로.  
**설치하기:** Claude·Codex·Grok을 쓰는 컴퓨터에서 `npx token-tv start`(또는 `uvx token-tv start`) 한 줄이면 됩니다. 로그인된 도구와 같은 와이파이의 시계를 스스로 찾고, 컴퓨터를 다시 켜도 계속 돌며, 대시보드를 엽니다. [라이브 데모](https://token-tv.vercel.app)에서 화면과 도구를 고르면 명령을 만들어 줍니다. AI에게 이 저장소를 주고 *"TokenTV 설정해줘"* 라고 해도 됩니다([AGENTS.md](AGENTS.md)).  
**내 화면 만들기:** 시계 없이 [Game Boy 예제](examples/gameboy)에서 시작해 AI에게 바꿔 달라고 하세요. [가이드](docs/clock-faces.md) · [공유하기](https://github.com/click6067-ship-it/token-tv/issues/new?template=share_a_face.md)  
자세히: [설정](docs/setup.ko.md) · [호환 시계](docs/hardware-compatibility.md) · [CodexBar 연동](docs/codexbar.md) · [애플워치](docs/apple-watch.md) · [English](README.md)  
**새 소식:** 새 화면과 지원 시계는 [릴리스](https://github.com/click6067-ship-it/token-tv/releases)로 나옵니다. 받아 보려면 Watch → Custom → Releases.  

<p align="center"><a href="examples/gameboy"><img src="examples/gameboy/comparison.png" width="640" alt="내 화면 만들기: 같은 샘플 사용량으로 그린 원래 픽셀 화면과 4색 Game Boy 예제"></a></p>
