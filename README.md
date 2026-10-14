# Doorbell Detector Notifier

A lightweight, local microphone detector that recognises an audible doorbell
chime and sends a notification through your ntfy server. It uses Python's
standard library and ALSA utilities; no cloud audio recognition is involved.

The included example profile recognises about **0.85 seconds of the opening
notes of a Nokia-style chime**. An eight-second cooldown suppresses its repeat
melody. Phone delivery adds delay after recognition.

## Requirements

- Linux with `arecord` and `amixer` (usually the `alsa-utils` package).
- Python 3.10 or newer.
- A microphone exposed as ALSA card `Device` with `Mic` and `Auto Gain Control`
  mixer controls. Adapt the capture command and mixer controls in `detector.py`
  for other devices.
- A reachable ntfy server and a topic subscribed to on your phone.

Capture uses 48 kHz, mono, signed 16-bit PCM. Startup sets gain to 12/16 and
disables AGC. Make sure these mixer settings are suitable for your microphone.
Live capture reserves the selected device and does not store recordings.

## Setup

```sh
git clone https://github.com/rocket6317/doorbell-detector-notifier.git "$HOME/doorbell-detector"
cd "$HOME/doorbell-detector"
cp config.example.json config.json
mkdir -p "$HOME/.config/doorbell-detector"
cp notifier.env.example "$HOME/.config/doorbell-detector/notifier.env"
chmod 600 "$HOME/.config/doorbell-detector/notifier.env"
```

Edit `config.json` for your ntfy server and the environment-file location.
The example uses a local server on port 6839. Set `NTFY_TOPIC` in the environment
file, and supply either `NTFY_TOKEN` or the publisher username/password if required.
Configuration and credentials are excluded from Git. Authentication follows the
[ntfy publishing API](https://docs.ntfy.sh/publish/).

Check the microphone and test notifications separately:

```sh
arecord -l
amixer -c Device
python3 detector.py live --seconds 30
python3 detector.py test-notify
python3 detector.py live --seconds 60 --notify
```

Replay, training, and tests never send notifications. Live mode publishes only
when `--notify` is supplied. Publishing runs separately from audio capture, uses
a five-second HTTP timeout, and attempts each alert once. Failures are logged.

## Calibrate using your actual chime

The included profile was tuned to one chime and microphone position. It is an
example, not a universal doorbell detector. Keep the microphone in its intended
position, disable AGC, and record both chimes and realistic background noise:

```sh
mkdir -p recordings
arecord -D hw:CARD=Device,DEV=0 -f S16_LE -r 48000 -c 1 -d 120 recordings/training.wav
```

Leave an initial quiet interval and ring several times with enough space for
each chime to finish. Identify an exact, distinctive sequence of opening notes.
Then train a template using its start/end times, in seconds. For example:

```sh
python3 detector.py train recordings/training.wav \
  --start 23.6 --end 24.45 --quiet-seconds 10 \
  --threshold 0.90 --output profile.json
python3 detector.py replay recordings/training.wav recordings/test.wav recordings/fans.wav
```

These start/end times refer to the example session. Use your own recording's
times, and inspect results on separate recordings. Training replaces `profile.json`.
Recognition measures nine frequency bands between 587 and 1397 Hz; other melodies
may need different `NOTES` values in the source. Quiet frames track slow ambient
changes. The matcher compares the ordered spectral pattern against its template.

Test fan noise, speech, television/music, door closures, and chimes under those
conditions. Shortening the sequence or lowering the threshold can increase false
alerts. Playing the same opening notes nearby may resemble the doorbell.

## Run continuously

The supplied service assumes the checkout is at `~/doorbell-detector`:

```sh
mkdir -p "$HOME/.config/systemd/user"
install -m 644 doorbell-detector.service "$HOME/.config/systemd/user/doorbell-detector.service"
systemctl --user daemon-reload
systemctl --user enable --now doorbell-detector.service
systemctl --user status doorbell-detector.service
journalctl --user -u doorbell-detector.service -n 50 --no-pager
```

For startup without an interactive login, check `loginctl show-user "$USER" -p Linger`.
If needed, enable it deliberately with `loginctl enable-linger "$USER"` according
to your host's policy. The unit permits at most two starts within five minutes
and stops after repeated capture failures. After fixing a failure, use
`systemctl --user reset-failed doorbell-detector.service` before starting again.

Stop with `systemctl --user stop doorbell-detector.service`; disable automatic
startup with `systemctl --user disable doorbell-detector.service`.
After changing code or the profile, restart the service to load the changes.

## Tests and validation

```sh
python3 -m unittest discover -s tests -v
```

See [TESTING.md](TESTING.md) and [VALIDATION.md](VALIDATION.md).
The [GitHub Actions template](ci/github-actions-tests.yml) runs the automated
tests on Python 3.10 and 3.14. To activate it, copy it to
`.github/workflows/tests.yml` using an account/token with workflow-write permission.
It is provided as a template and is not active in this initial publication.
Home recordings and credentials are intentionally not included. The detector
is an additional alert path; keep the existing doorbell operational while assessing
recognition in your own home.

## Optional link when tapping an alert

No camera or camera app is required. By default the detector sends a plain
doorbell notification. The optional `notification_click` setting adds ntfy's
`Click` header. Leave it empty to keep the default behaviour. Only set a link after checking
that your phone opens it as intended. URLs with spaces must be percent-encoded.

On iPhone, an Apple Shortcuts link can launch a shortcut containing an
**Open App** action for your chosen app. For example, name the shortcut
**Open Camera**, run it once manually to confirm it opens your app, then set:

```json
"notification_click": "shortcuts://run-shortcut?name=Open%20Camera"
```

Restart the detector after changing its config, and send `python3 detector.py
test-notify` to check tapping a real notification. The phone may need to be
unlocked. Camera selection, video, and two-way audio are handled inside the camera
app; this link does not select a particular camera or start talking automatically.

References: [ntfy click actions](https://docs.ntfy.sh/publish/#click-action) and
[Apple Shortcuts URL scheme](https://support.apple.com/en-gb/guide/shortcuts/apd624386f42/ios).

## Optional privacy hardening

The default user service does not store live audio, but microphone access still
follows your account's permissions. For a shared Linux host, see the optional
[dedicated-account setup](privacy/README.md). It limits normal microphone access
to a non-login detector account and adds service restrictions. Root administrators
can still override Linux permissions. Hardware mute or unplugging disables detection.
