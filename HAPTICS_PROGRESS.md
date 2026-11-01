# DualSense HD haptics: progress (branch `dualsense-hd-haptics`)

Working notes for this fork branch. Dropped before any upstream pull request.

## Scope
- USB only. Bluetooth is out of scope (handled by the separate "DualSense Controls" app).
- Off by default: `ds_haptics = 1` in `totk.ini` (or `TOTK_DS_HAPTICS=1`) turns it on. `ds_haptics_strength` = 10..100 (default 100).
- Every other pad, a DualSense over Bluetooth, or a DualSense whose audio device can't be opened keeps the normal SDL rumble.

## What changed
- `runtime/ds_haptics.c/.h` (new): finds the DualSense's 4-channel USB audio device, opens a 48 kHz F32 SDL3 stream, and
  synthesises 2 sines per side on channels 2/3 from the raw VibrationValue (DSP adapted from RenHDrum, MIT).
- `runtime/ov_input.c` `rumble_update`: hands both raw sides to `ds_haptics_take` first; when it takes them, the motors stay off.
- `runtime/input.c` `scan_pads` + `input_pad_dualsense_usb()`: flags a DualSense/Edge (054c:0ce6 / 054c:0df2) on a wired connection.
- `runtime/cfg.c`, `totk.ini.example`, `docs/controls.md`: the two settings (ini/env only, no menu row yet).
- `THIRD_PARTY_NOTICES.md`: RenHDrum row.

## Status
- [x] Code written; the four changed C files compile without warnings (clang cross-compile, -Wall, SDL3 headers). Not linked or run.
- [x] Test setup: `.github/workflows/ds-haptics-setup.yml` takes upstream TotK-Setup v0.2.8, compiles the 4 changed files with its own llvm (clean), swaps them into runtime/libtotkrt.a and publishes a prerelease (first: ds-haptics-081c7db). Fork-only, drop before upstream PR.
- [ ] Base recomp tested on the user's PC (upstream build, no haptics).
- [ ] This branch built on Windows (MSYS2 UCRT64) and run with `ds_haptics = 0`: must behave the same as upstream.
- [ ] Run with `ds_haptics = 1` + DualSense on USB: check `logs/totk.log` for `ds_haptics:` lines and feel the haptics.

## What to look for in totk.log
- `ds_haptics: using audio device "..." (4 channels, 48000 Hz)` then `ds_haptics: HD haptics on`: working path.
- `... has N channels, not the four ...` or `no DualSense USB audio device found`: the audio endpoint wasn't usable; it falls back to rumble.
- `waiting for a DualSense connected by USB`: SDL doesn't see the pad as wired DualSense.

## Known risks / next
- Opening the audio stream happens on the first vibration (one-time small hitch possible).
- SDL's own PS5 driver rumble is sent as 0 while HD haptics run; confirm no fighting/buzz.
- Possible follow-ups: an in-game menu toggle, tuning the curve/strength after the user tests it.

## DualSense button prompts (fork only, untested)
tools/port_ui_mod.py + DualSense-UI.bat: takes the changed textures of a 1.1.x prompt mod's Common blarc
(StavaasEVG's Dualsense UI, gamebanana 445517) and its Font External.bfotf into the 1.4.3 files, on top of
romfs-patches; output romfs-patches-dualsense, loaded with romfs_patches = <folder>. Report in logs/dualsense-ui.json.
2026-11-01: v1 (fonts + same-shape textures) crashed 1.4.3 at start (null read, after nvn init); fonts now opt-in
(--fonts). Textures now go in by BNTX transplant (mod's format/size, data appended to BRTD) for a checked list of 19
(PS face buttons, L1/L2, d-pad, R1/R2, prompt bases, DualSense picture); verified by decoding the 1.4.3 output.

2026-11-01: textures-only output crashed at the title too: the archive grew 0.9 MB past its RESTBL entry (the fonts
likely did the same at start). The tool now also writes the newest rsizetable with grown entries.

2026-11-01: textures + fonts work in game (with RESTBL). Callout points were off: the tool now copies the mod's values
into anim/Pa(SystemController|ActionGuide)_00_*.bflan curves that match key for key (73 curves).
Partial curve merge misplaced labels (the mod also adds curves). The mod's whole bflan is taken when it animates every curve the game's does.
