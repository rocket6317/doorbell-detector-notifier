"""Deterministic tests: no microphone, network, credentials, or recordings."""
import base64
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

import detector


ROOT = Path(__file__).resolve().parents[1]


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / 'profile.json').read_text())
        self.matcher = detector.Matcher(copy.deepcopy(self.profile))

    def melody(self, vectors=None):
        events = []
        for vector in vectors if vectors is not None else self.profile['template']:
            # Invert feature() to exercise both noise gating and pattern matching.
            energy = [n * 4 * math.exp(5 * v) for n, v in zip(self.matcher.noise, vector)]
            event = self.matcher.feed(energy)
            if event:
                events.append(event)
        return events

    def until(self, seconds):
        while self.matcher.frame * detector.HOP / detector.RATE < seconds:
            self.matcher.feed(list(self.matcher.noise))

    def test_ordered_profile_recognized_with_prefix_latency(self):
        events = self.melody()
        self.assertEqual([e['kind'] for e in events], ['doorbell'])
        self.assertAlmostEqual(events[0]['score'], 1.0, places=3)
        self.assertLessEqual(events[0]['time'], 0.85)

    def test_second_melody_suppressed_and_later_press_allowed(self):
        self.assertEqual(self.melody()[0]['kind'], 'doorbell')
        self.until(4)
        self.assertEqual([e['kind'] for e in self.melody()], ['melody'])
        self.until(10)
        self.assertEqual([e['kind'] for e in self.melody()], ['doorbell'])

    def test_melody_debounce(self):
        self.melody()
        self.assertEqual(self.melody(), [])

    def test_silence_and_ambient_drift_rejected(self):
        for _ in range(200):
            self.assertIsNone(self.matcher.feed([0] * len(detector.NOTES)))
        self.assertLess(self.matcher.noise[0], self.profile['noise'][0])

    def test_sustained_note_rejected(self):
        vectors = [[0] * 8 + [1] for _ in range(100)]
        self.assertEqual(self.melody(vectors), [])

    def test_reverse_order_rejected(self):
        self.assertEqual(self.melody(list(reversed(self.profile['template']))), [])

    def test_half_prefix_rejected(self):
        self.assertEqual(self.melody(self.profile['template'][:len(self.profile['template']) // 2]), [])
        self.until(3)
        self.assertLess(self.matcher.best, self.profile['threshold'])

    def test_legacy_pair_required(self):
        self.matcher.profile['require_pair'] = True
        self.assertEqual(self.melody()[0]['kind'], 'melody')
        self.until(4)
        self.assertEqual(self.melody()[0]['kind'], 'doorbell')

    def test_legacy_pair_outside_window_rejected(self):
        self.matcher.profile['require_pair'] = True
        self.assertEqual(self.melody()[0]['kind'], 'melody')
        self.until(6)
        self.assertEqual(self.melody()[0]['kind'], 'melody')

    def test_empty_or_all_zero_profile_rejected(self):
        for template in [[], [[0] * len(detector.NOTES)]]:
            with self.subTest(template=template):
                profile = copy.deepcopy(self.profile)
                profile['template'] = template
                with self.assertRaisesRegex(ValueError, 'nonempty tonal template'):
                    detector.Matcher(profile)


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'profile.json'
        self.output.write_text('existing-profile-sentinel')
        self.args = SimpleNamespace(wav='synthetic.wav', start=0.5, end=0.65,
                                    quiet_seconds=0.5, threshold=0.9, output=str(self.output))
        self.energies = [[1.0] * len(detector.NOTES) for _ in range(20)]
        for index, note in enumerate([8, 7, 6], start=10):
            self.energies[index][note] = 100.0

    def run_train(self):
        with mock.patch.object(detector, 'wav_frames', return_value=iter(self.energies)), \
                mock.patch.object(detector, 'powers', side_effect=lambda frame: frame), \
                contextlib.redirect_stdout(io.StringIO()):
            detector.train(self.args)

    def test_invalid_ranges_preserve_existing_profile(self):
        for start, end in [(-0.1, 0.5), (0.5, 0.5), (0.65, 0.5),
                           (0.5, 1.1), (1.1, 1.2), (0.501, 0.502)]:
            with self.subTest(start=start, end=end):
                self.args.start, self.args.end = start, end
                with self.assertRaises(ValueError):
                    self.run_train()
                self.assertEqual(self.output.read_text(), 'existing-profile-sentinel')

    def test_invalid_quiet_interval_preserves_existing_profile(self):
        for seconds in [-1, 0, 0.01, 1.1]:
            with self.subTest(seconds=seconds):
                self.args.quiet_seconds = seconds
                with self.assertRaisesRegex(ValueError, 'Quiet interval'):
                    self.run_train()
                self.assertEqual(self.output.read_text(), 'existing-profile-sentinel')

    def test_invalid_threshold_preserves_existing_profile(self):
        for threshold in [-1, 0, 1.01, float('nan')]:
            with self.subTest(threshold=threshold):
                self.args.threshold = threshold
                with self.assertRaisesRegex(ValueError, 'threshold'):
                    self.run_train()
                self.assertEqual(self.output.read_text(), 'existing-profile-sentinel')

    def test_nontonal_training_preserves_existing_profile(self):
        self.args.start, self.args.end = 0.0, 0.15
        with self.assertRaisesRegex(ValueError, 'Too few tonal frames'):
            self.run_train()
        self.assertEqual(self.output.read_text(), 'existing-profile-sentinel')

    def test_valid_training_produces_three_ordered_tonal_frames(self):
        self.run_train()
        profile = json.loads(self.output.read_text())
        self.assertEqual(profile['noise'], [1.0] * len(detector.NOTES))
        self.assertEqual(len(profile['template']), 3)
        self.assertEqual([frame.index(max(frame)) for frame in profile['template']], [8, 7, 6])
        self.assertEqual(profile['threshold'], 0.9)
        self.assertEqual(profile['training_file'], 'synthetic.wav')
        self.assertFalse(profile['require_pair'])


class AudioTests(unittest.TestCase):
    def test_known_tone_has_peak_at_expected_note(self):
        samples = [int(10000 * math.sin(2 * math.pi * 1047 * i / detector.RATE))
                   for i in range(detector.HOP)]
        energy = detector.powers(samples)
        peak = detector.NOTES.index(1047)
        self.assertEqual(max(range(len(energy)), key=energy.__getitem__), peak)
        self.assertGreater(energy[peak], 100 * max(e for i, e in enumerate(energy) if i != peak))

    def test_decode_little_endian_pcm(self):
        self.assertEqual(list(detector.decode(b'\x01\x00\xff\xff\x00\x80')), [1, -1, -32768])

    def test_wav_rejects_wrong_rate_channels_and_width(self):
        with tempfile.TemporaryDirectory() as directory:
            for rate, channels, width in [(44100, 1, 2), (48000, 2, 2), (48000, 1, 1)]:
                with self.subTest(rate=rate, channels=channels, width=width):
                    path = Path(directory) / 'test.wav'
                    with wave.open(str(path), 'wb') as wav:
                        wav.setframerate(rate)
                        wav.setnchannels(channels)
                        wav.setsampwidth(width)
                        wav.writeframes(b'\0' * 4800)
                    with self.assertRaisesRegex(ValueError, '48 kHz, mono, 16-bit'):
                        list(detector.wav_frames(path))

    def test_wav_reads_complete_hops_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setframerate(detector.RATE)
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.writeframes(b'\x01\x00' * (detector.HOP + 5))
            frames = list(detector.wav_frames(path))
            self.assertEqual(len(frames), 1)
            self.assertEqual(list(frames[0]), [1] * detector.HOP)


class NotificationTests(unittest.TestCase):
    def test_env_comments_quotes_export_and_home_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'notifier.env'
            path.write_text("# comment\nexport NTFY_TOPIC=doorbell # comment\nNTFY_PUBLISHER_PASSWORD='space # $literal'\nEMPTY=\n")
            with mock.patch('pathlib.Path.expanduser', return_value=path) as expanduser:
                values = detector.load_env('~/notifier.env')
            expanduser.assert_called_once()
            self.assertEqual(values, {'NTFY_TOPIC': 'doorbell', 'NTFY_PUBLISHER_PASSWORD': 'space # $literal', 'EMPTY': ''})

    def publish(self, env, test=False):
        response = mock.MagicMock()
        response.__enter__.return_value = io.StringIO('{"id":"test-id"}')
        with mock.patch.object(detector, 'load_env', return_value=env), \
                mock.patch.object(detector.urllib.request, 'urlopen', return_value=response) as urlopen, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            detector.publish({'notification_env': 'unused', 'notification_server': 'http://localhost:6839/'}, test=test)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'http://localhost:6839/doorbell')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(urlopen.call_args.kwargs, {'timeout': 5})
        self.assertEqual(json.loads(output.getvalue())['kind'], 'notification_accepted')
        return request

    def test_bearer_auth_takes_precedence(self):
        request = self.publish({'NTFY_TOPIC': 'doorbell', 'NTFY_TOKEN': 'fake-token',
                                'NTFY_PUBLISHER_USER': 'fake-user', 'NTFY_PUBLISHER_PASSWORD': 'fake-password'})
        self.assertEqual(request.get_header('Authorization'), 'Bearer fake-token')
        self.assertEqual(request.get_header('Priority'), 'high')
        self.assertEqual(request.data, b'Someone rang the doorbell.')

    def test_basic_auth_and_test_notification(self):
        request = self.publish({'NTFY_TOPIC': 'doorbell', 'NTFY_PUBLISHER_USER': 'fake-user',
                                'NTFY_PUBLISHER_PASSWORD': 'fake password'}, test=True)
        auth = 'Basic ' + base64.b64encode(b'fake-user:fake password').decode()
        self.assertEqual(request.get_header('Authorization'), auth)
        self.assertEqual(request.get_header('Title'), 'Doorbell test')
        self.assertEqual(request.get_header('Priority'), 'default')

    def test_public_topic_without_auth(self):
        self.assertIsNone(self.publish({'NTFY_TOPIC': 'doorbell'}).get_header('Authorization'))

    def test_invalid_topic_rejected_before_network(self):
        for topic in ['', 'nested/topic']:
            with self.subTest(topic=topic), mock.patch.object(detector, 'load_env', return_value={'NTFY_TOPIC': topic}), \
                    mock.patch.object(detector.urllib.request, 'urlopen') as urlopen:
                with self.assertRaises(ValueError):
                    detector.publish({'notification_env': 'unused', 'notification_server': 'http://localhost:6839'})
                urlopen.assert_not_called()

    def test_failure_logging_does_not_include_exception_message(self):
        exc = RuntimeError('secret-token and private destination')
        exc.code = 503
        with mock.patch.object(detector, 'publish', side_effect=exc), contextlib.redirect_stdout(io.StringIO()) as output:
            detector.publish_safely({})
        self.assertEqual(json.loads(output.getvalue()), {'kind': 'notification_failed', 'error_type': 'RuntimeError', 'http_status': 503})
        self.assertNotIn('secret-token', output.getvalue())


if __name__ == '__main__':
    unittest.main()
