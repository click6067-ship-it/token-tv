# Hardware compatibility

Only what has been checked on a real clock is listed as verified. Everything else is unknown,
not "probably fine".

## Verified units

One card per clock checked with TokenTV on real hardware. "Not checked" means nobody has tried it on that unit,
not that it fails. `token-tv start` prints your clock's model and firmware, and says when that pair is not on a
card yet.

### The author's SD_PRO (GeekMagic SmallTV-style, 240×240)

| Field | |
| --- | --- |
| Clock | A SmallTV-style Wi-Fi clock bought on a Korean AliExpress discount (receipt: ₩5,650; prices vary by region) |
| Firmware | Stock, with the **SD_PRO** web UI and a photo album; it reports no version number |
| What TokenTV uses | `/theme/list`, `/photo/list`, `/photo/upload`, photo theme id `2` |
| Still / GIF | Both: still faces and the animated GIF faces (Arcade, Space) |
| Restore | `token-tv run --restore-display` is covered by the fake-clock contract test; a restore on this unit is not recorded |
| Host | Linux |
| Date | 2026-10-02 onwards |
| Evidence | [photo of the running clock](images/real-clock.jpg) |

### SmallTV-Ultra on Ultra-V9.0.54 (#7, @yethihahtwe)

| Field | |
| --- | --- |
| Clock | GeekMagic **SmallTV-Ultra** (`/v.json` reports `SmallTV-Ultra`) |
| Firmware | Stock `Ultra-V9.0.54` |
| What TokenTV uses | `/app.json`, `/album.json`, `/doUpload?dir=/image/`, `/set?img=`, Photo Album theme `3` |
| Still / GIF | Still: the Pixel Retro face (upload HTTP 200, display receipt). Animated: not checked on this unit |
| Restore | Not checked |
| Host | Not reported |
| Date | 2026-10-12 |
| Evidence | Photos, the firmware screen and a display receipt: [#7](https://github.com/click6067-ship-it/token-tv/pull/7#issuecomment-6117957156) |

### A new SmallTV-Ultra with no /app.json yet, on a Raspberry Pi 4 (#10, @okalentiev)

| Field | |
| --- | --- |
| Clock | GeekMagic **SmallTV-Ultra**, new: its theme had never been changed, so `/app.json` answered 404 |
| Firmware | Stock `Ultra-V9.0.54` |
| Still / GIF | Both: Digital (JPEG) and Space (animated GIF, about 208 kB, upload HTTP 200, plays on the clock) |
| Restore | Not checked on the clock; the new-unit backup and restore (no saved theme) ran only against a fake clock |
| Host | Raspberry Pi 4, Debian 13 arm64, Python 3.13, TokenTV 0.2.0 from PyPI as a systemd user service |
| Date | 2026-10-16 |
| Evidence | [#10](https://github.com/click6067-ship-it/token-tv/pull/10) |

### SmallTV-Ultra on the pre-release firmware 9.1.54 (#7, @yethihahtwe)

| Field | |
| --- | --- |
| Clock | The same GeekMagic **SmallTV-Ultra** as the V9.0.54 card, updated |
| Firmware | GeekMagic's pre-release `9.1.54` (the "NEW WEB UI" pre-release) |
| Still / GIF | A TokenTV face shows on the clock (video); which kind is not stated |
| Restore | Not checked |
| Host | Not reported |
| Date | 2026-10-27 |
| Evidence | [video in #7](https://github.com/click6067-ship-it/token-tv/pull/7#issuecomment-6433844118) |

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
- SmallTV-Ultra on firmware other than `Ultra-V9.0.54` and the pre-release `9.1.54`.
- Restoring the original theme on a real SmallTV-Ultra.
- Firmware without the photo album page or with different photo API paths.
- macOS and Windows hosts.

## Check your own clock before connecting accounts

1. Open the clock's address (shown on its screen) in a browser on the same network.
2. Look for a photo album / photo upload page. Without one, TokenTV cannot draw on it.
3. `npx token-tv demo` needs no clock and no login. `npx token-tv start` then looks for the clock on
   your Wi-Fi, or asks for its address, and checks its form before writing anything.

Tried another model or firmware? Please open a [Hardware compatibility issue](https://github.com/click6067-ship-it/token-tv/issues/new?template=hardware_compatibility.md)
(`.github/ISSUE_TEMPLATE/hardware_compatibility.md`) with the model, the firmware, the faces you tried and
the result: your report becomes the next card. Leave out Wi-Fi names, passwords and public IP addresses.

## What you need besides the clock

A computer that stays on in the same network, with Claude Code, Codex or the Grok CLI signed in, and
Node for `npx` (the launcher brings its own Python if it needs one). The clock only shows the picture;
the computer reads usage and draws it, so while the computer sleeps the clock keeps its last picture.
