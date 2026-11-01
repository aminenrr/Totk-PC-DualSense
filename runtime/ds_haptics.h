// DualSense HD haptics over USB (runtime/ds_haptics.c): the game's raw HD rumble values played on the DualSense's two
// voice-coil actuators through the controller's USB audio endpoint, instead of the two-motor SDL rumble.
// Off unless TOTK_DS_HAPTICS=1; with it on, it only takes over while a DualSense (or DualSense Edge) is the open gamepad,
// connected by USB, and its four-channel audio endpoint opened. Otherwise ds_haptics_take returns 0 and the caller keeps
// the SDL rumble path (runtime/ov_input.c rumble_update).
#pragma once
#include <stdint.h>

// One side of nn::hid::VibrationValue as the game sent it: amplitudes 0..1, frequencies in Hz.
typedef struct { float amp_low, freq_low, amp_high, freq_high; } DsHapticsSide;

// Called by runtime/ov_input.c rumble_update (under its vib_lock) with both sides, a silent side (stale, vibration not
// permitted, rumble strength 0) passed as amplitude 0. Returns 1 when the HD path took the values, 0 when the caller
// must drive the SDL rumble motors instead. Opens or closes the audio stream as the setting and the gamepad change.
// The values stay in force for 250 ms; with no newer call the actuators go silent by themselves.
int ds_haptics_take(const DsHapticsSide side[2]);
