"""Finite normal-ground walk track; native STATIC order on a 20Hz clock.

Rate samples old velocity before physics; playback advances after physics.
Original newborn/script writers, idle/attack blending and business gates are
outside this track. No asset IO or rendering clock belongs here.
"""
from dataclasses import dataclass
import math

from bugbits.sim.motion import length
from bugbits.sim.nectar import f32


@dataclass
class WalkAnimation:
    duration: float
    base_speed: float
    ratio: float
    phase: float = 0.
    rate: float = 1.
    playing: bool = False
    selected: bool = False
    loop_count: int = 0

    def __post_init__(self):
        self.duration, self.base_speed, self.ratio = map(
            f32, (self.duration, self.base_speed, self.ratio))
        if not all(math.isfinite(v) for v in (self.duration, self.base_speed, self.ratio)) \
                or self.duration <= 0:
            raise ValueError('walk track requires finite configuration and positive duration')

    def select_walk(self, old_velocity):
        if not self.selected:
            self.phase, self.loop_count = 0., 0
            self.selected, self.playing = True, True
        # 4AB87B uses 4012B0's velocity norm, then one f32 rate store.
        self.rate = f32(f32(length(old_velocity)) * self.ratio + self.base_speed)

    def leave_walk(self):
        # The engineering controller has no idle/mixing track yet. Retain its
        # old walk phase for audit; the next walk selection restarts track0.
        self.selected, self.playing = False, False

    def advance(self, dt):
        if not self.playing:
            return
        self.phase = f32(self.phase + self.rate * f32(dt))
        # 44D100: strict >, exactly ONE subtraction, never modulo/while.
        if self.phase > self.duration:
            self.loop_count += 1
            self.phase = f32(self.phase - self.duration)

    def snapshot(self):
        return {'scope': 'normal-ground-walk-track-f32-20hz-v1', 'clip': 'walk',
                'phase': self.phase, 'rate': self.rate, 'duration': self.duration,
                'baseSpeed': self.base_speed, 'ratio': self.ratio,
                'playing': self.playing, 'selected': self.selected,
                'loop': True, 'loopCount': self.loop_count,
                'rateSample': 'old-velocity-before-physics',
                'advanceStage': 'after-physics'}
