<h1 align="center">TokenTV</h1>
<p align="center">
  <a href="https://github.com/click6067-ship-it/token-tv/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/click6067-ship-it/token-tv"></a>
  <a href="https://github.com/click6067-ship-it/token-tv/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <a href="https://hackaday.com/2026/10/06/smalltv-hacking-with-surprisingly-little-fuss/"><img alt="Featured on Hackaday" src="https://img.shields.io/badge/featured%20on-Hackaday-1a1a1a"></a>
  <a href="https://github.com/steipete/CodexBar#desk-display"><img alt="Listed in CodexBar" src="https://img.shields.io/badge/listed%20in-CodexBar-555555"></a>
</p>

<p align="center"><b>Your Claude and Codex usage limits on a ~$5 Wi-Fi desk clock. No firmware flashing.</b></p>

<p align="center"><a href="https://youtube.com/shorts/FN5DLILYiI0"><img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/docs/images/real-clock-shorts.jpg" width="240" alt="TokenTV on a real clock: a 16-second video"></a> <img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/docs/images/arcade.gif" width="240" alt="The animated Arcade face (sample data): Clawd, the Codex cloud, Grok, Copilot and Anti at work, each picture also a gauge"></p>

**New: Arcade.** Each character's picture is its gauge; under it, what it is doing, a battery of what is left and the reset time.

**Try it:** [live demo](https://token-tv.vercel.app) or `npx token-tv demo`, no clock or login needed.  
**Set it up:** run `npx token-tv start` (or `uvx token-tv start`) on a computer that stays on. It finds your signed-in tools and the clock on your Wi-Fi, keeps running in the background and opens your dashboard. Or tell your AI *"Set up TokenTV for me"* ([AGENTS.md](https://github.com/click6067-ship-it/token-tv/blob/main/AGENTS.md)).

**You need:**
- A GeekMagic SmallTV, SD_PRO or Ultra ([which ones work](https://github.com/click6067-ship-it/token-tv/blob/main/docs/hardware-compatibility.md)).
- Claude Code, Codex or the Grok CLI, signed in on that computer. A browser login alone is not enough ([setup](https://github.com/click6067-ship-it/token-tv/blob/main/docs/setup.md)).
- [Node](https://nodejs.org/), for `npx`. It brings its own Python if it needs one.

Your logins stay on your computer: TokenTV asks each service with the login its own CLI saved, and the clock only ever receives a picture.

<p align="center"><img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/docs/images/real-clock.jpg" alt="Digital, Pixel Retro and Sci-Fi HUD on the real clock"></p>
<p align="center"><img src="https://raw.githubusercontent.com/click6067-ship-it/token-tv/main/docs/images/four-faces.png" alt="Four of the faces: Digital, Neon, Pixel Retro and Sci-Fi HUD (sample data)"></p>

**Update:** `npx token-tv update` (or `uvx token-tv update`) keeps your config and logins.  
**Make your own face** from the [Game Boy example](https://github.com/click6067-ship-it/token-tv/tree/main/examples/gameboy) with your AI ([guide](https://github.com/click6067-ship-it/token-tv/blob/main/docs/clock-faces.md)).  
More: [setup and options](https://github.com/click6067-ship-it/token-tv/blob/main/docs/setup.md) · [how it works](https://github.com/click6067-ship-it/token-tv/blob/main/docs/stock-photo-display.md) · [CodexBar (Copilot, Antigravity)](https://github.com/click6067-ship-it/token-tv/blob/main/docs/codexbar.md) · [Apple Watch](https://github.com/click6067-ship-it/token-tv/blob/main/docs/apple-watch.md) · [한국어](https://github.com/click6067-ship-it/token-tv/blob/main/README.ko.md)
