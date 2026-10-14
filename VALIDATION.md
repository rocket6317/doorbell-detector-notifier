# Initial validation

The example profile was built from one chime recording at 48 kHz mono, gain
12/16, AGC off. A second recording captured three further button presses while
the host fans were reported to be running at a mid-high level.

| Recorded condition | Expected presses | Detected alerts |
| --- | ---: | ---: |
| Original capture, including door closure overlapping a final melody | 3 | 3 |
| Separate capture with fans | 3 | 3 |
| 90 seconds of fans | 0 | 0 |
| 20 seconds of ambient noise | 0 | 0 |

The original two-melody mode was tested live and delivered a phone notification.
The user requested lower latency. Opening lengths of 0.60, 0.75, 0.85, and 1.00
seconds were compared. The shortest candidate also accepted a reversed test
sequence. The 0.85-second template at threshold 0.90 was selected for better
rejection margin while retaining sub-second recognition.

All 13 final local validation checks passed both locally and on the deployment
host, including recorded-press counts, early recognition, duplicate suppression,
an incomplete opening, a reversed opening, a reversed melody, a sustained tone,
loud broadband spectral noise, and an isolated door-slam excerpt. Some adverse
tests use constructed spectral sequences and do not replace household tests.

The final live test produced one doorbell event and one accepted ntfy message.
The second melody was recognised but did not publish another alert. The user
confirmed phone delivery and acceptable speed. Button-to-phone latency was not
instrumented; 0.85 seconds describes the recognition window after audible onset.

Initial live capture used about 5% of one CPU core and 27 MB peak memory on the
test host. The original persistent service averaged about 3% of one core over
several minutes. Resource use varies by hardware.

The separate chime capture was used to compare candidate opening lengths, so it
is not an untouched holdout for the final choice. Negative recordings total only
110 seconds; no daily false-alert rate has been established. Speech, television,
music, different fan speeds, and changed microphone placement require further
testing. Raw home audio, credentials, and deployment identifiers are not published.

`validate.py` preserves the original session's regression checks. It expects
private captures named `training.wav`, `test.wav`, `fans.wav`, and `ambient.wav`
with the original timing. It is not a general validator for arbitrary recordings;
use `detector.py replay` and your own expected event times when calibrating a new
installation. The automated CI tests do not require these private recordings.

## Camera-app link validation

Optional `notification_click` support passed all 28 automated tests. The
deployment candidate also passed nine notification tests. A real ntfy test
message contained the configured Apple Shortcuts URL, and the user confirmed
that tapping it opened the chosen camera app on the iPhone. The existing recognition profile
was unchanged. Specific-camera selection and two-way audio remain inside the camera app;
neither is started automatically by the app-launch link.

## Optional account isolation

The dedicated-account setup was applied to the original Linux deployment.
The detector's root-managed service is enabled and captures audio as its own
non-login account, with zero automatic restarts at verification. Normal user
access to the microphone and private server recordings was denied. Service
properties confirmed read-only system files, hidden home directories, restricted
devices, no privilege escalation, and network access limited to localhost.

Physical ringing after that migration and actual reboot/unplug persistence have
not yet been confirmed. The public hardening files are optional manual templates,
not a universal installer. Raw recordings previously copied to other machines or
backups need separate protection. These controls do not restrict root administrators.
