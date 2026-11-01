# TotK Recomp

**TotK Recomp** is a static recompilation of *The Legend of Zelda: Tears of the Kingdom* (Nintendo Switch, 2023) into a native Windows x86-64 application ([docs/architecture.md](docs/architecture.md)).

> [!IMPORTANT]
> **No game files are included.** You need your own legally obtained copy of *Tears of the Kingdom*, dumped from your own console: the base game and the 1.2.1 or 1.4.3 update. Instructions for obtaining those files will not be provided.
>
> The game is built from your files on your machine, so the result contains the game. It is for your own use. Do not share it.

## This fork: DualSense additions

> [!NOTE]
> This is a fork of [valentderah/totk-pc-recomp](https://github.com/valentderah/totk-pc-recomp) with DualSense extras: PlayStation button prompts, the touchpad as a bindable button, impulse-trigger-style vibration in the adaptive triggers, and experimental HD haptics. Tested on game update 1.4.3. Test builds are on the [Releases](https://github.com/aminenrr/Totk-PC-DualSense/releases) page (`TotK-Setup-0.2.8-dshaptics-<commit>-windows.zip`). Run the setup on your install folder the same way as upstream. A rerun keeps your romfs, saves and `totk.ini`.

### What's added

- **PlayStation button prompts**: a tool that ports a DualSense UI mod onto your own 1.4.3 files (see below).
- **Touchpad as a button**: the touchpad click is a gamepad button of its own (`touchpad` in `totk.ini`). To use it as Minus instead of the Create/Share button, press F1, open the bindings, select the gamepad cell of Minus, and press the touchpad.
- **Impulse triggers on DualSense**: the Xbox impulse-trigger rumble now has a DualSense version. With "Trigger vibration (Xbox)" on in the F1 menu (`rumble_triggers = 1` under `[input]`), the adaptive triggers vibrate along with the rumble, as strong as the right motor, the same signal the Xbox triggers get. It works over USB.
- **HD haptics over USB (experimental)**: drives the DualSense's voice coils from the game's HD Rumble data. It works, but it still feels like a plain coil buzz rather than Joy-Con HD Rumble, so it is off by default. To try it, add the following under `[input]` (USB only):

  ```ini
  ds_haptics = 1
  ds_haptics_strength = 200   ; 10..200
  ds_haptics_curve = 0.4      ; 0.3..1, lower makes weak vibrations stronger
  ds_haptics_freq = 100       ; 25..100 %
  ```

### Installing the DualSense UI

1. Download **StavaasEVG's Dualsense UI** from GameBanana: <https://gamebanana.com/mods/445517>. Pick a colour, such as `stavaasevg_s_dualsense_ui_black.zip`, and unzip it.
2. Run this from the unzipped setup folder, giving your install folder and the mod's folder (or its `romfs` folder inside it):

   ```bat
   DualSense-UI.bat "C:\Games\TotK" "C:\Downloads\stavaasevg_s_dualsense_ui_black"
   ```

   It should print `"status": "pass"`. It writes `romfs-patches-dualsense` in the install folder, with a report in `logs\dualsense-ui.json`. It takes the mod's button and controller textures, its button font, and its controller-picture callouts. It also grows the game's resource size table to fit them, and keeps the 60 fps patches of `romfs-patches`.
3. In `totk.ini`, add:

   ```ini
   [files]
   romfs_patches = C:\Games\TotK\romfs-patches-dualsense
   ```

4. Start the game. To undo it, delete that line. After rerunning the setup (an update), run `DualSense-UI.bat` again rather than restoring an old copy of the folder.

The mod was made for game version 1.1. The tool doesn't copy its layouts or shaders, only the parts listed above.

## Status

Early development. The game is playable on Windows; visual bugs and crashes are still expected.

Report problems as issues, following [CONTRIBUTING.md](CONTRIBUTING.md).

## Features

- Native code, not emulation
- Game updates 1.2.1 and 1.4.3, with saves that carry over between them
- 60 fps by default; up to 144 fps or the monitor's refresh rate (experimental)
- Custom resolutions (1080p, 2k...), supersampling and AMD FSR 1 upscaling
- 16:10 (Steam Deck, handhelds), 21:9 and 32:9 (ultrawide) game resolutions, with the camera and the interface in that shape
- In-game settings menu (F1) and performance overlay (F10)
- Keyboard, mouse and gamepad with remapping, rumble and gyro
- Xbox button prompts: a layout that keeps the Switch button positions and shows the Xbox labels
- Shaders prepared at install instead of during play

## Planned

- Linux and the Steam Deck
- Mods made for emulators: unpack a mod into a `mods` folder
- VRR

## Installing

Requirements: Windows 10 or later, an x86-64 CPU with AVX2, a GPU with Vulkan 1.3 and `VK_EXT_external_memory_host`, about 36 GiB free during setup (20 GiB after).

1. Download `TotK-Setup-<version>-windows.zip` from [Releases](../../releases/latest) and unpack it.
2. Start `TotK-Setup.exe`. If SmartScreen warns about an unsigned app, choose *More info*, then *Run anyway*.
3. Pick your game files, the language and an install folder, and press *Start*. The setup builds the game once.
4. Play `totk.exe` from the install folder.

To update, run a newer `TotK-Setup.exe` on the same folder; saves and settings are kept. Settings are in the in-game menu and in `totk.ini` ([totk.ini.example](totk.ini.example) lists every key). Controls: [docs/controls.md](docs/controls.md).

## Credits

TotK Recomp builds on the projects below. What was taken from each, with its license, is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- [LAS Recomp](https://github.com/peiikai/LASRecomp)
- [MacNativeGames](https://github.com/ly05010419/MacNativeGames)
- [d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile) and [nxnative](https://github.com/seedds/nxnative)
- [SavageWindRecomp](https://github.com/Revivedx/SavageWindRecomp)
- [Ryujinx](https://github.com/Ryujinx/Ryujinx)
- [deko3d](https://github.com/devkitPro/deko3d)
- [hactool](https://github.com/SciresM/hactool)
- [SDL 3](https://libsdl.org), [Dear ImGui](https://github.com/ocornut/imgui), [AMD FSR 1](https://github.com/GPUOpen-Effects/FidelityFX-FSR), [Vulkan Memory Allocator](https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator), [libopus](https://opus-codec.org), [libvpx](https://chromium.googlesource.com/webm/libvpx), [Zstandard](https://github.com/facebook/zstd)
- [Switchbrew](https://switchbrew.org) and the Switch homebrew community

## License

The project's own code is under the [MIT License](LICENSE); third-party code keeps its own license ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). The license grants nothing for Nintendo's game.

TotK Recomp is an independent, non-commercial fan project, not affiliated with or endorsed by Nintendo. *The Legend of Zelda*, *Tears of the Kingdom* and *Nintendo Switch* are trademarks of Nintendo.

## Building from source

[docs/building.md](docs/building.md) lists the toolchain and the steps. Everything the build writes stays under `build\` and `generated\`, which git ignores; run `tools/check_content.py` before a commit. Testers: [docs/tester-guide.md](docs/tester-guide.md).

Most of the code and documentation is written by AI coding agents (Claude Code) under the maintainer's direction; the maintainer plays every build and decides what is merged. [AGENTS.md](AGENTS.md) holds the rules they work under.
