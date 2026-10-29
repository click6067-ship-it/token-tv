# Hardware compatibility

Only what has been checked on a real clock is listed as verified. Everything else is unknown,
not "probably fine".

## Verified

| Clock | Firmware web UI | What TokenTV uses | Checked |
| --- | --- | --- | --- |
| The author's 240×240 GeekMagic SmallTV-style Wi-Fi clock (receipt: ₩5,650 on a Korean AliExpress discount; prices vary by region) | Stock firmware with the **SD_PRO** web UI and a photo album | `/theme/list`, `/photo/list`, `/photo/upload`, photo theme id `2` | One unit, Linux host |
| GeekMagic **SmallTV-Ultra** | Stock firmware `Ultra-V9.0.54` (`/v.json` reports `SmallTV-Ultra`) | `/app.json`, `/album.json`, `/doUpload?dir=/image/`, `/set?img=`, Photo Album theme `3` | The contributor's unit, running this release's code: photos and a display receipt in [#7](https://github.com/click6067-ship-it/token-tv/pull/7). A second unit on a Raspberry Pi 4 (Linux aarch64), static and animated (GIF) faces: [#10](https://github.com/click6067-ship-it/token-tv/pull/10). The author has no Ultra |

TokenTV never flashes firmware and never deletes your photos. It uploads one picture, switches the
clock to its photo theme, and `token-tv run --restore-display` puts the original theme back.

On the SmallTV-Ultra, TokenTV also turns the album's autoplay off while it is showing. Restoring puts
the theme and autoplay back, but there is no known way to read which photo was selected before, so
TokenTV's picture can stay in the album. Delete `tokentv.jpg` / `tokentv.gif` on the clock's image page
if you want them gone.

The Ultra has one picture file, not the SD_PRO's three: each new animated face is written over the one the
clock is playing, and TokenTV cannot list the Ultra's files to check that it arrived whole. This is how the
contributors' units ran; if an Ultra ever freezes on a picture, turn it off and on.

On the SD_PRO, leave TokenTV's `tokentv*.gif` files alone in the album while TokenTV runs: it switches them
itself, and one turned on by hand can be the next file TokenTV writes while the clock plays it.

A new SmallTV-Ultra has no `/app.json` (it answers 404) until its theme is changed for the first time.
TokenTV then records that there was no saved theme, switches to the Photo Album as usual, and on restore
puts autoplay back but leaves the theme alone. Pick a theme on the clock's settings page afterwards if you
want a different one.

## Not verified

- Other GeekMagic models, SmallTV Pro, and clones that look the same. A similar case is not evidence
  of the same firmware.
- SmallTV-Ultra on firmware other than `Ultra-V9.0.54`.
- Firmware without the photo album page or with different photo API paths.
- macOS and Windows hosts.

## Check your own clock before connecting accounts

1. Open the clock's address (shown on its screen) in a browser on the same network.
2. Look for a photo album / photo upload page. Without one, TokenTV cannot draw on it.
3. `npx token-tv demo` needs no clock and no login. `npx token-tv start` then looks for the clock on
   your Wi-Fi, or asks for its address, and checks its form before writing anything.

Tried another model? Please open a **Hardware compatibility** issue with the model, the firmware
web UI name and the result. Leave out Wi-Fi names, passwords and public IP addresses.

## What you need besides the clock

A computer that stays on in the same network, with Claude Code, Codex or the Grok CLI signed in, and
Node for `npx` (the launcher brings its own Python if it needs one). The clock only shows the picture;
the computer reads usage and draws it, so while the computer sleeps the clock keeps its last picture.
