# Changelog

## [1.0.1.0] - 2026-10-14

### Added

- Optionally open a user-selected app or website when tapping a doorbell alert.
- Keep link support disabled by default; no camera is needed for doorbell notifications.
- Provide generic dedicated-account service and microphone-permission templates.
- Test optional links and reject malformed URLs before sending notifications.

## [1.0.0.0] - 2026-10-14

### Added

- Recognise the opening notes of an audible doorbell and send an ntfy alert.
- Suppress repeated melodies from a single button press.
- Capture locally with ALSA and run persistently as a systemd user service.
- Train a spectral template from a recording and test recordings without sending alerts.
- Provide an example Nokia-chime profile, configuration examples, and automated tests.
