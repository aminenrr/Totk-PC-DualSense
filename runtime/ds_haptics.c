// The synthesis below (ds_curve, ds_side, ds_next) is adapted from RenHDrum src/dualsense/haptics.rs
// (make_side, DualSenseHapticsDsp::next_sample) @ d4ae23d1cd2e25b49d549ce9c5487f24f0a9aad3
// (MIT OR Apache-2.0, used here under MIT, Copyright (c) 2026 Three-Dola).
//
// DualSense HD haptics over USB (ds_haptics.h). Plugged in by USB, the DualSense shows up as a four-channel 48 kHz audio
// device: channels 0 and 1 are the speaker and headset, channels 2 and 3 drive the left and right voice-coil actuators.
// Each side of the game's VibrationValue becomes two sine waves (the low and the high band at the game's own
// frequencies), so the controller plays the HD rumble the Switch would instead of runtime/ov_input.c rumble_update's
// two-motor reduction. The game's amplitude goes through a power curve (TOTK_DS_HAPTICS_CURVE, default 0.5: RenHDrum's
// square root, weak pulses stay felt; 1 is linear and keeps the game's dynamics), the two bands of a side are scaled to
// sum at most 1, and the frequencies are scaled by TOTK_DS_HAPTICS_FREQ percent (the Joy-Con's actuators resonate near
// 160 and 320 Hz, the DualSense's lower, so a lower setting moves the bands where its coils are strongest). Amplitude
// and frequency follow their targets with a 4 ms one-pole smoothing. TOTK_DS_HAPTICS_STRENGTH is in percent of 0.8 of
// full scale (10 to 200); the output is clipped at full scale. Every 10 s with vibration, the log gets one line with the
// value count, frequency ranges and peak amplitude the game sent, for tuning.
// Bluetooth is not handled here: over Bluetooth the controller has no audio endpoint, and the SDL rumble path stays.
#include <math.h>
#include <stdint.h>
#include <string.h>
#include <SDL3/SDL.h>

#include "cfg.h"
#include "ds_haptics.h"
#include "host.h"
#include "input.h"
#include "platform/platform.h"

enum { DS_RATE = 48000, DS_CHANNELS = 4, DS_LEFT = 2, DS_RIGHT = 3, DS_CHUNK = 256 };
#define DS_CEILING 0.8f
#define DS_SMOOTHING_MS 4.0
#define DS_MIN_HZ 20.0f
#define DS_MAX_HZ 1000.0f
#define DS_STALE_NS 250000000ull      // like rumble_update: values not renewed for 250 ms are silent
#define DS_RETRY_NS 5000000000ull     // a failed open is tried again at most every 5 s

typedef struct { double phase_low, phase_high; float amp_low, amp_high, freq_low, freq_high; } DsVoice;

static PlatMutex ds_lock = PLAT_MUTEX_INIT;   // the targets, shared with the audio callback
static DsHapticsSide target[2];                // ds_lock: after ds_side
static uint64_t target_at;                     // ds_lock: plat_now_ns of the last ds_haptics_take, 0 none
static float gain = DS_CEILING;                // ds_lock

// Game thread: the curve and frequency settings, and the tuning statistics.
static float curve_exp = 0.5f, freq_scale = 1;
static struct { uint64_t since; unsigned values; float lo_min, lo_max, hi_min, hi_max, peak; } stats;

// Audio thread only.
static DsVoice voice[2] = {{0, 0, 0, 0, 160, 320}, {0, 0, 0, 0, 160, 320}};
static float smoothing;

// Game thread (rumble_update, serialized by ov_input.c's vib_lock).
static SDL_AudioStream *stream;
static int audio_init;
static uint64_t next_try;
static unsigned cfg_seen = ~0u;
static int enabled;
static volatile int32_t logged_off, logged_fail;

// RenHDrum make_side: square root of the clamped amplitude, the two bands scaled to sum at most 1, frequencies clamped
// to 20..1000 Hz with the neutral 160 / 320 Hz for a missing one.
static float ds_curve(float a) { return a > 0 ? powf(a < 1 ? a : 1, curve_exp) : 0; }   // NaN -> 0
static float ds_hz(float f, float neutral) {
    if (!(f > 0)) return neutral;
    return f < DS_MIN_HZ ? DS_MIN_HZ : f > DS_MAX_HZ ? DS_MAX_HZ : f;
}
static DsHapticsSide ds_side(const DsHapticsSide *v) {
    DsHapticsSide s = {ds_curve(v->amp_low), ds_hz(ds_hz(v->freq_low, 160) * freq_scale, 160),
                       ds_curve(v->amp_high), ds_hz(ds_hz(v->freq_high, 320) * freq_scale, 320)};
    float sum = s.amp_low + s.amp_high;
    if (sum > 1) s.amp_low /= sum, s.amp_high /= sum;
    return s;
}

// RenHDrum DualSenseHapticsDsp::next_sample: amplitude and frequency follow the target, two sines summed and clamped.
static float ds_next(DsVoice *v, const DsHapticsSide *t, float g) {
    float k = smoothing;
    v->amp_low += (t->amp_low - v->amp_low) * k;
    v->amp_high += (t->amp_high - v->amp_high) * k;
    v->freq_low += (t->freq_low - v->freq_low) * k;
    v->freq_high += (t->freq_high - v->freq_high) * k;
    v->phase_low += v->freq_low / (double)DS_RATE;
    v->phase_high += v->freq_high / (double)DS_RATE;
    if (v->phase_low >= 1) v->phase_low -= 1;
    if (v->phase_high >= 1) v->phase_high -= 1;
    double x = v->amp_low * sin(2 * M_PI * v->phase_low) + v->amp_high * sin(2 * M_PI * v->phase_high);
    x *= g;
    return (float)(x < -1 ? -1 : x > 1 ? 1 : x);
}

// SDL audio callback: fills what the device asks for, in chunks of DS_CHUNK frames, taking the targets once per chunk
// (about 5.3 ms, like RenHDrum's slots). Speaker and headset channels stay silent.
static void SDLCALL ds_pull(void *user, SDL_AudioStream *s, int additional, int total) {
    (void)user, (void)total;
    float buf[DS_CHUNK * DS_CHANNELS];
    int frames = additional / (int)(DS_CHANNELS * sizeof(float));
    while (frames > 0) {
        int n = frames < DS_CHUNK ? frames : DS_CHUNK;
        DsHapticsSide t[2];
        float g;
        uint64_t now = plat_now_ns();
        plat_mutex_lock(&ds_lock);
        t[0] = target[0], t[1] = target[1], g = gain;
        int live = target_at && now - target_at <= DS_STALE_NS;
        plat_mutex_unlock(&ds_lock);
        if (!live) t[0].amp_low = t[0].amp_high = t[1].amp_low = t[1].amp_high = 0;
        for (int i = 0; i < n; i++) {
            float *f = &buf[i * DS_CHANNELS];
            f[0] = f[1] = 0;
            f[DS_LEFT] = ds_next(&voice[0], &t[0], g);
            f[DS_RIGHT] = ds_next(&voice[1], &t[1], g);
        }
        if (!SDL_PutAudioStreamData(s, buf, (int)(n * DS_CHANNELS * sizeof(float)))) break;
        frames -= n;
    }
}

static void ds_close(const char *why) {
    if (!stream) return;
    SDL_DestroyAudioStream(stream);
    stream = NULL;
    plat_mutex_lock(&ds_lock);
    target_at = 0;
    plat_mutex_unlock(&ds_lock);
    rt_log("ds_haptics: closed (%s), SDL rumble again", why);
}

// The DualSense's playback device: its name names the controller ("DualSense Wireless Controller" on Windows, also
// "Wireless Controller" on older drivers) and it has at least four channels. 0 when none is found.
static SDL_AudioDeviceID ds_find_device(void) {
    int n = 0;
    SDL_AudioDeviceID *ids = SDL_GetAudioPlaybackDevices(&n), found = 0;
    for (int i = 0; ids && i < n && !found; i++) {
        const char *name = SDL_GetAudioDeviceName(ids[i]);
        if (!name || !(SDL_strcasestr(name, "DualSense") || SDL_strcasestr(name, "Wireless Controller"))) continue;
        SDL_AudioSpec spec;
        int frames = 0;
        if (!SDL_GetAudioDeviceFormat(ids[i], &spec, &frames) || spec.channels < DS_CHANNELS) {
            rt_log("ds_haptics: \"%s\" has %d channels, not the four of the USB haptics endpoint", name,
                   SDL_GetAudioDeviceFormat(ids[i], &spec, &frames) ? spec.channels : 0);
            continue;
        }
        found = ids[i];
        rt_log("ds_haptics: using audio device \"%s\" (%d channels, %d Hz)", name, spec.channels, spec.freq);
    }
    SDL_free(ids);
    return found;
}

static int ds_open(void) {
    if (!audio_init) {
        if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
            if (!plat_xchg32(&logged_fail, 1)) rt_log("ds_haptics: SDL audio init failed (%s): SDL rumble", SDL_GetError());
            return 0;
        }
        audio_init = 1;
    }
    SDL_AudioDeviceID dev = ds_find_device();
    if (!dev) {
        if (!plat_xchg32(&logged_fail, 1))
            rt_log("ds_haptics: no DualSense USB audio device found: SDL rumble (retrying every 5 s)");
        return 0;
    }
    smoothing = (float)(1 - exp(-1000.0 / (DS_RATE * DS_SMOOTHING_MS)));
    SDL_AudioSpec spec = {SDL_AUDIO_F32, DS_CHANNELS, DS_RATE};
    stream = SDL_OpenAudioDeviceStream(dev, &spec, ds_pull, NULL);
    if (!stream || !SDL_ResumeAudioStreamDevice(stream)) {
        rt_log("ds_haptics: opening the haptics stream failed (%s): SDL rumble", SDL_GetError());
        if (stream) SDL_DestroyAudioStream(stream);
        stream = NULL;
        return 0;
    }
    plat_xchg32(&logged_fail, 0);
    rt_log("ds_haptics: HD haptics on (USB, strength %.0f%%)", (double)(gain / DS_CEILING * 100));
    return 1;
}

int ds_haptics_take(const DsHapticsSide side[2]) {
    unsigned v = cfg_version();
    if (v != cfg_seen) {
        cfg_seen = v;
        enabled = cfg_bool("TOTK_DS_HAPTICS");
        double pct = cfg_double("TOTK_DS_HAPTICS_STRENGTH");
        pct = pct < 10 ? 10 : pct > 200 ? 200 : pct;
        double ce = cfg_double("TOTK_DS_HAPTICS_CURVE"), fr = cfg_double("TOTK_DS_HAPTICS_FREQ");
        curve_exp = (float)(ce >= 0.3 && ce <= 1.0 ? ce : ce > 1.0 ? 1.0 : ce > 0 ? 0.3 : 0.5);
        freq_scale = (float)((fr >= 25 && fr <= 100 ? fr : fr > 100 ? 100 : fr > 0 ? 25 : 100) / 100);
        rt_log("ds_haptics: settings strength %.0f%%, curve %.2f, frequency %.0f%%", pct, (double)curve_exp,
               (double)(freq_scale * 100));
        plat_mutex_lock(&ds_lock);
        gain = DS_CEILING * (float)(pct / 100);
        plat_mutex_unlock(&ds_lock);
        next_try = 0;
    }
    if (!enabled) { ds_close("setting off"); return 0; }
    if (!input_pad_dualsense_usb()) {
        if (!plat_xchg32(&logged_off, 1)) rt_log("ds_haptics: on, waiting for a DualSense connected by USB");
        ds_close("no DualSense on USB");
        return 0;
    }
    plat_xchg32(&logged_off, 0);
    uint64_t now = plat_now_ns();
    if (!stream) {
        if (now < next_try) return 0;
        next_try = now + DS_RETRY_NS;
        if (!ds_open()) return 0;
    }
    for (int s = 0; s < 2; s++) {
        const DsHapticsSide *v = &side[s];
        if (!(v->amp_low > 0.01f || v->amp_high > 0.01f)) continue;
        if (!stats.values) stats.lo_min = stats.hi_min = 1e9f, stats.lo_max = stats.hi_max = stats.peak = 0;
        stats.values++;
        if (v->freq_low < stats.lo_min) stats.lo_min = v->freq_low;
        if (v->freq_low > stats.lo_max) stats.lo_max = v->freq_low;
        if (v->freq_high < stats.hi_min) stats.hi_min = v->freq_high;
        if (v->freq_high > stats.hi_max) stats.hi_max = v->freq_high;
        if (v->amp_low > stats.peak) stats.peak = v->amp_low;
        if (v->amp_high > stats.peak) stats.peak = v->amp_high;
    }
    if (!stats.since) stats.since = now;
    if (now - stats.since >= 10000000000ull) {
        if (stats.values)
            rt_log("ds_haptics: last 10 s: %u values, low band %.0f-%.0f Hz, high band %.0f-%.0f Hz, peak amplitude %.2f",
                   stats.values, (double)stats.lo_min, (double)stats.lo_max, (double)stats.hi_min, (double)stats.hi_max,
                   (double)stats.peak);
        stats.values = 0, stats.since = now;
    }
    DsHapticsSide t[2] = {ds_side(&side[0]), ds_side(&side[1])};
    plat_mutex_lock(&ds_lock);
    target[0] = t[0], target[1] = t[1], target_at = now;
    plat_mutex_unlock(&ds_lock);
    return 1;
}
