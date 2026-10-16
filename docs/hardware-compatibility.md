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
3. `token-tv demo` needs no clock and no login. `token-tv setup` then asks for the clock address
   (`http://<ip>`) and checks its form before writing anything.

Tried another model? Please open a **Hardware compatibility** issue with the model, the firmware
web UI name and the result. Leave out Wi-Fi names, passwords and public IP addresses.

## What you need besides the clock

A computer that stays on in the same network (Python 3.10+). The clock only shows the picture;
the computer reads usage and draws it.
