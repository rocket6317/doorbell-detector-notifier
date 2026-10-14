# Testing

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

The suite uses only the Python standard library. It does not use ALSA, make network
requests, read live credentials, or require household recordings. Temporary WAV
fixtures are generated and removed during tests. The provided GitHub Actions
template at `ci/github-actions-tests.yml` runs the suite on Python 3.10 and 3.14
when copied to `.github/workflows/tests.yml` with workflow-write permission.
It is not active in the initial publication. Local tests were run on Python 3.14.

Tests reconstruct ordered energy vectors from the published profile to exercise
the real feature gate and matcher, including prefix recognition, melody debounce,
repeat suppression, later presses, legacy pair confirmation, silence, sustained
tones, incomplete prefixes, and reverse ordering. Audio tests verify a known tone,
PCM decoding, format rejection, and complete WAV frame handling. Mocked notification
tests cover environment parsing, request destination, authentication precedence,
timeouts, test messages, invalid topics, and sanitized failure logging.
Training tests verify timestamp and quiet-interval bounds, threshold validation,
rejection of empty or nontonal templates, preservation of an existing output on
failed training, and successful creation of an ordered three-note profile.

These deterministic checks do not establish acoustic performance in another room.
The sample profile must be calibrated against local doorbell and ambient recordings.
Live capture recovery, service startup, phone delivery, and rejection of arbitrary
household sounds require deployment tests; see VALIDATION.md for the original
installation's validation boundaries.
