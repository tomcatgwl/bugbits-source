"""Finite STATIC setlight arithmetic on an engineering 20 Hz clock.

Packed colors use R143's /256 quantization; scalar/degree slots use R142's
linear mix. This does not name selected device lights or emulate x87 timing.
Positive-duration interruptions retain the last committed base (R137/R141).
"""
import copy
import math
import re
import struct


def _tick(tick):
    if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        raise ValueError('light tick must be a nonnegative integer')
    return tick


def _request(tokens):
    if (not isinstance(tokens, (list, tuple)) or len(tokens) != 9
            or any(not isinstance(v, str) or v.split() != [v] for v in tokens)):
        raise ValueError('setlight requires nine single tokens')
    if any(re.fullmatch(r'[0-9a-fA-F]+', v) is None for v in tokens[1:4]):
        raise ValueError('setlight colors require unsigned hex digits')
    try:
        duration = float(tokens[0])
        values = [float(v) for v in tokens[4:]]
    except ValueError as error:
        raise ValueError('invalid setlight numeric token') from error
    if duration < 0 or not all(math.isfinite(v) for v in [duration, *values]):
        raise ValueError('setlight numeric tokens must be finite; duration nonnegative')
    # Original 445070 -> 412E8D/412C33 unsigned conversion saturates on
    # overflow; four actual levels contain the ten-digit white ffffffffff.
    return duration, {'colors': [min(int(v, 16), 0xFFFFFFFF) for v in tokens[1:4]],
                      'scalars': [values[0], values[4]], 'anglesDegrees': values[1:4]}


def _mix_color(start, target, ratio):
    # 47C054 stores the ratio as a DWORD float before 460EA3's *255/trunc.
    ratio = struct.unpack('<f', struct.pack('<f', ratio))[0]
    k = int(255 * ratio)
    return sum((((((start >> shift) & 255) * (255 - k)
                  + ((target >> shift) & 255) * k) >> 8) << shift)
               for shift in (0, 8, 16, 24))


class LightState:
    """Accept requests, advance monotonic ticks, return detached JSON state."""

    def __init__(self):
        self.tick = 0
        self.current = None
        self.target = None
        self.start = None
        self.duration = self.elapsed = 0.0

    def accept(self, tokens, tick, source):
        duration, target = _request(tokens)
        tick = _tick(tick)
        if tick < self.tick or not isinstance(source, str) or not source:
            raise ValueError('invalid light request source/tick')
        if self.current is None and duration != 0:
            raise ValueError('transition requires an explicit initial zero-duration state')
        self.advance(tick)
        self.request_tick, self.source = tick, source
        self.tokens = list(tokens)
        self.requested_duration = duration
        self.target = target
        self.duration, self.elapsed = duration, 0.0
        if duration == 0:
            self.current = copy.deepcopy(target)
            self.start = copy.deepcopy(target)
        else:
            self._evaluate()

    def _evaluate(self):
        ratio = self.elapsed / self.duration
        self.current = {'colors': [_mix_color(a, b, ratio)
                                   for a, b in zip(self.start['colors'], self.target['colors'])]}
        for field in ('scalars', 'anglesDegrees'):
            self.current[field] = [a * (1 - ratio) + b * ratio
                                   for a, b in zip(self.start[field], self.target[field])]

    def advance(self, tick):
        tick = _tick(tick)
        if tick < self.tick:
            raise ValueError('light ticks must be monotonic')
        self.tick = tick
        if self.current is not None and self.duration:
            # Integer tick subtraction avoids accumulation drift at equality.
            self.elapsed = (tick - self.request_tick) / 20
            if self.elapsed > self.duration:
                self.current = copy.deepcopy(self.target)
                self.start = copy.deepcopy(self.target)
                self.duration = self.elapsed = 0.0
            else:
                self._evaluate()

    def snapshot(self):
        if self.current is None:
            return None
        return copy.deepcopy({'version': 'setlight-state-v1',
                              'scope': 'fixed-20hz-static-setlight-v1',
                              'tick': self.tick, 'requestTick': self.request_tick,
                              'source': self.source, 'sourceTokens': self.tokens,
                              'current': self.current, 'target': self.target,
                              'transitionElapsed': self.elapsed, 'duration': self.duration,
                              'requestedDuration': self.requested_duration,
                              'transitionActive': self.duration != 0})
