<h1 align="center">TokenTV</h1>
<p align="center">
  <a href="https://github.com/click6067-ship-it/token-tv/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/click6067-ship-it/token-tv"></a>
  <a href="https://github.com/click6067-ship-it/token-tv/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <a href="https://hackaday.com/2026/10/06/smalltv-hacking-with-surprisingly-little-fuss/"><img alt="Featured on Hackaday" src="https://img.shields.io/badge/featured%20on-Hackaday-1a1a1a"></a>
  <a href="https://github.com/steipete/CodexBar#desk-display"><img alt="Listed in CodexBar" src="https://img.shields.io/badge/listed%20in-CodexBar-555555"></a>
</p>

<p align="center"><img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/docs/images/real-clock.jpg" alt="TokenTV on a real tiny desk clock"></p>
<p align="center"><img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/docs/images/arcade.gif" width="320" alt="The animated Arcade face (sample data): Clawd, the Codex cloud, Grok, Copilot and Anti at work, each picture also a gauge"></p>
<p align="center"><img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/docs/images/clock-faces.png" alt="Some of the clock faces (sample data)"></p>

Your Claude and Codex usage limits (plus Grok, and Copilot or Antigravity through CodexBar) on a ~$5 Wi-Fi desk clock. No firmware flashing.  
**New: Arcade**, an animated face where each character's picture is also its gauge, with a few rare scenes that open only when their moment comes on your clock.  
**Try it:** [live demo](https://token-tv.vercel.app), `npx token-tv demo` or `uvx token-tv demo`, no clock or login needed.

**What you need:**
- A GeekMagic SmallTV (SD_PRO or Ultra) on your Wi-Fi ([which ones work](https://github.com/click6067-ship-it/token-tv/blob/main/docs/hardware-compatibility.md)).
- A computer that stays on, where Claude Code, Codex or the Grok CLI is installed and signed in. A claude.ai or chatgpt.com login in the browser is not enough: install [Claude Code](https://code.claude.com/docs/en/quickstart) or Codex (`npm install -g @openai/codex`) and sign in with the same account. On a Mac, Claude in the browser can do through [CodexBar](https://github.com/click6067-ship-it/token-tv/blob/main/docs/codexbar.md#claude-in-the-browser-only-on-a-mac-experimental) (experimental).
- [Node](https://nodejs.org/), for `npx`. Nothing else: the launcher brings its own Python if it needs one.

On Windows, run it on the side where your claude or codex is signed in: Windows itself with Node is simplest, and WSL stops soon after its last terminal closes.  
While the computer sleeps, the clock keeps its last picture. Your logins stay on your computer: TokenTV asks each
service for your usage with the login its own CLI saved, and the clock only ever receives a picture.

**Set it up:** run `npx token-tv start` (or `uvx token-tv start`) on the computer where you use Claude, Codex or Grok. It finds your signed-in tools and the clock on your Wi-Fi, offers to keep running after you close the terminal and after a restart, and opens your dashboard. Pick a face and tools on the [live demo](https://token-tv.vercel.app) and it writes the command for you. Or give this repo to your AI and say *"Set up TokenTV for me."* ([AGENTS.md](https://github.com/click6067-ship-it/token-tv/blob/main/AGENTS.md))  
**Make your own face:** no clock needed, start from the [Game Boy example](https://github.com/click6067-ship-it/token-tv/tree/main/examples/gameboy) and ask your AI to change it. [Guide](https://github.com/click6067-ship-it/token-tv/blob/main/docs/clock-faces.md) · [Share it](https://github.com/click6067-ship-it/token-tv/issues/new?template=share_a_face.md)  
Details: [how it works](https://github.com/click6067-ship-it/token-tv/blob/main/docs/stock-photo-display.md) · [setup](https://github.com/click6067-ship-it/token-tv/blob/main/docs/setup.md) · [compatible clocks](https://github.com/click6067-ship-it/token-tv/blob/main/docs/hardware-compatibility.md) · [CodexBar input](https://github.com/click6067-ship-it/token-tv/blob/main/docs/codexbar.md) · [Apple Watch](https://github.com/click6067-ship-it/token-tv/blob/main/docs/apple-watch.md) · [한국어](https://github.com/click6067-ship-it/token-tv/blob/main/README.ko.md)  
**Updates:** new faces and supported clocks ship as [releases](https://github.com/click6067-ship-it/token-tv/releases). To get them, use Watch → Custom → Releases.  

<p align="center"><a href="https://github.com/click6067-ship-it/token-tv/tree/main/examples/gameboy"><img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/examples/gameboy/comparison.png" width="640" alt="Change a face: original pixel style and a four-colour Game Boy example, rendered from the same sample readings"></a></p>
