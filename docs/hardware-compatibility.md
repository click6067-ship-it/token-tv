# Hardware compatibility

Only what has been checked on a real clock is listed as verified. Everything else is unknown,
not "probably fine".

## Verified

| Clock | Firmware web UI | What TokenTV uses | Checked |
| --- | --- | --- | --- |
| The author's 240×240 GeekMagic SmallTV-style Wi-Fi clock (bought on an AliExpress sale for about ₩6,000 / $5) | Stock firmware with the **SD_PRO** web UI and a photo album | `/theme/list`, `/photo/list`, `/photo/upload`, photo theme id `2` | One unit, Linux host |

TokenTV never flashes firmware and never deletes your photos. It uploads one picture, switches the
clock to its photo theme, and `token-tv run --restore-display` puts the original theme back.

## Not verified

- Other GeekMagic models, SmallTV Pro, and clones that look the same. A similar case is not evidence
  of the same firmware.
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
