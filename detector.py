#!/usr/bin/env python3
"""Local ALSA melody matcher. Standard library only; never stores live audio."""
import argparse
import array
import base64
import collections
import concurrent.futures
import functools
import json
import math
from pathlib import Path
import shlex
import signal
import statistics
import subprocess
import sys
import time
import urllib.request
import wave

RATE = 48000
HOP = 2400
WINDOW = 2048
NOTES = [587, 698, 784, 880, 932, 1047, 1175, 1244, 1397]
TAPER = [0.5 - 0.5 * math.cos(2 * math.pi * i / (WINDOW - 1)) for i in range(WINDOW)]


@functools.lru_cache(None)
def roots(n):
    return [complex(math.cos(-2 * math.pi * k / n), math.sin(-2 * math.pi * k / n)) for k in range(n // 2)]


def fft(x):
    n = len(x)
    if n == 1:
        return x
    even, odd = fft(x[::2]), fft(x[1::2])
    terms = [r * v for r, v in zip(roots(n), odd)]
    return [a + b for a, b in zip(even, terms)] + [a - b for a, b in zip(even, terms)]


def powers(samples):
    spectrum = fft([samples[i] * TAPER[i] / 32768 for i in range(WINDOW)])
    energy = [abs(x) ** 2 for x in spectrum[:WINDOW // 2]]
    return [sum(energy[k] for k in range(round(f * WINDOW / RATE) - 1, round(f * WINDOW / RATE) + 2)) for f in NOTES]


def wav_frames(path):
    with wave.open(str(path), 'rb') as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
            raise ValueError('Expected 48 kHz, mono, 16-bit PCM WAV')
        while True:
            data = w.readframes(HOP)
            if len(data) < HOP * 2:
                break
            yield decode(data)


def decode(data):
    samples = array.array('h', data)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples


def feature(energy, noise):
    ratios = [e / max(n, 1e-9) for e, n in zip(energy, noise)]
    if max(ratios) < 8:
        return [0.0] * len(NOTES)
    values = [max(0.0, math.log(max(r, 1e-9) / 4)) for r in ratios]
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm else values


class Matcher:
    def __init__(self, profile):
        self.profile = profile
        self.noise = list(profile['noise'])
        self.template = profile['template']
        if not self.template or not any(any(frame) for frame in self.template):
            raise ValueError('Profile needs a nonempty tonal template; retrain with valid timestamps')
        self.history = collections.deque(maxlen=len(self.template))
        self.frame = 0
        self.last_melody = -100.0
        self.pending = None
        self.last_press = -100.0
        self.best = 0.0

    def feed(self, energy):
        now = self.frame * HOP / RATE
        self.frame += 1
        vec = feature(energy, self.noise)
        self.history.append(vec)
        # Track slow ambient drift only when no musical tone passes the gate.
        if not any(vec):
            self.noise = [0.999 * n + 0.001 * min(e, 2 * n) for n, e in zip(self.noise, energy)]
        if len(self.history) < len(self.template):
            return None
        active = [(a, b) for a, b in zip(self.template, self.history) if any(a)]
        score = sum(sum(x * y for x, y in zip(a, b)) for a, b in active) / len(active)
        self.best = max(self.best, score)
        if score < self.profile['threshold'] or now - self.last_melody < self.profile['melody_debounce']:
            return None
        self.last_melody = now
        event = {'kind': 'melody', 'time': round(now, 2), 'score': round(score, 3)}
        if not self.profile.get('require_pair', True):
            if now - self.last_press >= self.profile['press_cooldown']:
                self.last_press = now
                event['kind'] = 'doorbell'
            return event
        if self.pending is not None and self.profile['pair_min'] <= now - self.pending <= self.profile['pair_max']:
            self.pending = None
            if now - self.last_press >= self.profile['press_cooldown']:
                self.last_press = now
                event['kind'] = 'doorbell'
        else:
            self.pending = now
        return event


def load_env(path):
    result = {}
    for line in Path(path).expanduser().read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, sep, value = line.partition('=')
        if sep:
            parts = shlex.split(value, comments=True)
            result[key.strip()] = parts[0] if parts else ''
    return result


def publish(config, test=False):
    env = load_env(config['notification_env'])
    headers = {'Title': 'Doorbell test' if test else 'Doorbell', 'Priority': 'default' if test else 'high', 'Tags': 'bell'}
    if env.get('NTFY_TOKEN'):
        headers['Authorization'] = 'Bearer ' + env['NTFY_TOKEN']
    elif env.get('NTFY_PUBLISHER_USER') and env.get('NTFY_PUBLISHER_PASSWORD'):
        credentials = (env['NTFY_PUBLISHER_USER'] + ':' + env['NTFY_PUBLISHER_PASSWORD']).encode()
        headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode()
    topic = env['NTFY_TOPIC']
    if not topic or '/' in topic:
        raise ValueError('Invalid notification topic')
    request = urllib.request.Request(config['notification_server'].rstrip('/') + '/' + topic,
                                     data=('Doorbell microphone notification test.' if test else 'Someone rang the doorbell.').encode(),
                                     headers=headers, method='POST')
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    print(json.dumps({'kind': 'notification_accepted', 'id': result.get('id'), 'topic': topic}), flush=True)


def publish_safely(config):
    try:
        publish(config)
    except Exception as exc:
        # Never include credential-bearing request details in the journal.
        print(json.dumps({'kind': 'notification_failed', 'error_type': type(exc).__name__,
                          'http_status': getattr(exc, 'code', None)}), flush=True)


def replay(profile, path):
    matcher = Matcher(profile)
    events = []
    started = time.monotonic()
    for samples in wav_frames(path):
        event = matcher.feed(powers(samples))
        if event:
            events.append(event)
    return {'file': str(path), 'events': events, 'best_score': round(matcher.best, 3), 'analysis_seconds': round(time.monotonic() - started, 2)}


def train(args):
    if not 0 <= args.start < args.end:
        raise ValueError('Training timestamps must satisfy 0 <= start < end')
    if not 0 < args.threshold <= 1:
        raise ValueError('Match threshold must be greater than 0 and at most 1')
    energies = [powers(frame) for frame in wav_frames(args.wav)]
    start, end = round(args.start * RATE / HOP), round(args.end * RATE / HOP)
    quiet_count = int(args.quiet_seconds * RATE / HOP)
    if not 0 <= start < end <= len(energies):
        raise ValueError('Training sequence must contain frames within the recording')
    if not 0 < quiet_count <= len(energies):
        raise ValueError('Quiet interval must contain frames within the recording')
    quiet = energies[:quiet_count]
    noise = [max(statistics.median(e[k] for e in quiet), 1e-9) for k in range(len(NOTES))]
    template = [feature(e, noise) for e in energies[start:end]]
    if sum(any(v) for v in template) < len(template) * 0.6:
        raise ValueError('Too few tonal frames in template; inspect boundaries')
    profile = {'rate': RATE, 'hop': HOP, 'notes_hz': NOTES, 'noise': noise, 'template': template,
               'threshold': args.threshold, 'require_pair': False, 'melody_debounce': 3.0, 'pair_min': 3.4, 'pair_max': 4.8, 'press_cooldown': 8.0,
               'training_file': Path(args.wav).name, 'training_start': args.start, 'training_end': args.end}
    Path(args.output).write_text(json.dumps(profile, indent=2) + '\n')
    print(json.dumps({'profile': args.output, 'active_frames': sum(any(v) for v in template), 'total_frames': len(template)}))


def live(args, profile, config):
    # This changes only the selected USB card's capture controls.
    subprocess.run(['amixer', '-q', '-c', 'Device', 'sset', 'Mic', '12'], check=True)
    subprocess.run(['amixer', '-q', '-c', 'Device', 'sset', 'Auto Gain Control', 'off'], check=True)
    command = ['arecord', '-q', '-D', 'hw:CARD=Device,DEV=0', '-f', 'S16_LE', '-r', str(RATE), '-c', '1', '-t', 'raw']
    if args.seconds:
        command += ['-d', str(args.seconds)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    matcher = Matcher(profile)
    publisher = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    pending_publish = None
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
        process.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps({'kind': 'listening', 'notify': args.notify, 'card': 'Device'}), flush=True)
    try:
        while not stopped:
            data = process.stdout.read(HOP * 2)
            if len(data) < HOP * 2:
                break
            event = matcher.feed(powers(decode(data)))
            if event:
                event['wall_time'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
                print(json.dumps(event), flush=True)
                if args.notify and event['kind'] == 'doorbell':
                    # Capture must keep flowing while HTTP is in progress.
                    # The five-second HTTP timeout is shorter than the cooldown.
                    if pending_publish is None or pending_publish.done():
                        pending_publish = publisher.submit(publish_safely, config)
                    else:
                        print(json.dumps({'kind': 'notification_busy'}), flush=True)
        code = process.wait(timeout=5)
        if code and not stopped:
            raise RuntimeError(f'ALSA capture exited with status {code}')
        print(json.dumps({'kind': 'stopped', 'best_score': round(matcher.best, 3)}), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stdout.close()
        publisher.shutdown(wait=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default=str(Path(__file__).with_name('profile.json')))
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.json')))
    sub = parser.add_subparsers(dest='command', required=True)
    t = sub.add_parser('train')
    t.add_argument('wav'); t.add_argument('--start', type=float, required=True); t.add_argument('--end', type=float, required=True)
    t.add_argument('--quiet-seconds', type=float, default=10); t.add_argument('--output', required=True)
    t.add_argument('--threshold', type=float, default=0.90)
    r = sub.add_parser('replay'); r.add_argument('wav', nargs='+')
    l = sub.add_parser('live'); l.add_argument('--seconds', type=int); l.add_argument('--notify', action='store_true')
    sub.add_parser('test-notify')
    args = parser.parse_args()
    if args.command == 'train':
        train(args); return
    profile = json.loads(Path(args.profile).read_text())
    if args.command == 'replay':
        for path in args.wav:
            print(json.dumps(replay(profile, path)), flush=True)
    else:
        config = json.loads(Path(args.config).read_text())
        if args.command == 'test-notify':
            publish(config, test=True)
        else:
            live(args, profile, config)


if __name__ == '__main__':
    main()
