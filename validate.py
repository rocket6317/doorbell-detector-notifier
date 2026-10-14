"""Validate real captures and adversarial melody sequences; no notifications."""
import json
from pathlib import Path
import sys
import detector


def run(energies, profile):
    matcher = detector.Matcher(profile)
    events = []
    for energy in energies:
        event = matcher.feed(energy)
        if event:
            events.append(event)
    return events


def main(directory):
    profile = json.loads(Path(__file__).with_name('profile.json').read_text())
    directory = Path(directory)
    energies = {}
    results = []
    for name, expected in [('training.wav', 3), ('test.wav', 3),
                           ('fans.wav', 0), ('ambient.wav', 0)]:
        frames = [detector.powers(x) for x in detector.wav_frames(directory / name)]
        energies[name] = frames
        events = run(frames, profile)
        bells = [e for e in events if e['kind'] == 'doorbell']
        assert len(bells) == expected, (name, events)
        if expected:
            assert len(events) == 6, (name, events)
        results.append({'test': name, 'doorbell_alerts': len(bells), 'melodies': len(events), 'passed': True})
    source = energies['training.wav']
    quiet = source[20:200]
    melody = source[460:534]
    single = run(quiet + melody + quiet, profile)
    assert sum(e['kind'] == 'doorbell' for e in single) == 1, single
    results.append({'test': 'single_complete_melody', 'doorbell_alerts': 1, 'passed': True})
    for name in ['training.wav', 'test.wav']:
        bells = [e['time'] for e in run(energies[name], profile) if e['kind'] == 'doorbell']
        windows = [(24, 24.6), (35, 35.5), (43.8, 44.5)] if name == 'training.wav' else [(29, 29.5), (51, 51.5), (73.3, 73.9)]
        assert all(low <= when <= high for when, (low, high) in zip(bells, windows)), (name, bells)
        results.append({'test': 'prefix_latency_' + name, 'alert_times_seconds': bells, 'passed': True})
    prefix = source[472:489]
    for name, frames in [
        ('incomplete_prefix_pair', quiet + prefix[:7] + quiet[:40] + prefix[:7] + quiet),
        ('reversed_prefix_pair', quiet + list(reversed(prefix)) * 2 + quiet),
        ('reversed_melody_pair', quiet + list(reversed(melody)) * 2 + quiet),
        ('steady_loud_tone', [[n * (100 if k == 8 else 1) for k, n in enumerate(profile['noise'])]] * 400),
        ('door_slam_excerpt', quiet + source[970:1020] + quiet),
        ('broadband_loud_noise', [[n * 100 for n in profile['noise']]] * 400),
    ]:
        events = run(frames, profile)
        assert not any(e['kind'] == 'doorbell' for e in events), (name, events)
        results.append({'test': name, 'doorbell_alerts': 0, 'passed': True})
    print(json.dumps({'profile_training': profile['training_file'], 'results': results}, indent=2))


if __name__ == '__main__':
    main(sys.argv[1])
