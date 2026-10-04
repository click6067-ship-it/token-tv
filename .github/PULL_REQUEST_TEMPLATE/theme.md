## New clock face

- **id** (lowercase, used in `STYLES`):
- **name**:
- **author** (GitHub handle shown in the Gallery):
- **license** of any font or image you added:
- **source / inspiration** (link, or "original"):

### Checks

- [ ] Renderer added to `token_tv/themes.py` `RENDERERS` and the id to `STYLES` in `token_tv/display.py`
- [ ] 240×240 preview attached, rendered from sample data (`token-tv demo`), viewed at real size
- [ ] Missing readings show a dash, never `0%`; old readings are marked
- [ ] No credentials, real emails or real usage in code, images or this PR
- [ ] `python3 -B -m unittest discover -s tests` passes

The maintainer adds `added_at`, `min_version` and the likes issue to `token_tv/assets/theme-catalog.json`
when the face ships in a release. You can use your face from your own fork right away; see
`docs/clock-faces.md`.
