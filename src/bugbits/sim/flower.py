"""Normal ceFlower timer/edge and finite animation track; no rendering or IO.

R368 pinned original STATIC + normal VAN DATA. Runtime type changes, dynamic
attachments and full original world traversal are separate integration work.
"""
from dataclasses import dataclass
import math

from bugbits.sim.nectar import f32

# Normal model animation0, factor1, speed1, loopfalse. Original last key times.
NORMAL_TRACKS = {1: (30., f32(3.3), 4.333333492279053),
                 2: (15., f32(3.4), 4.599999904632568),
                 3: (15., f32(2.8), 3.933333396911621)}


@dataclass
class FlowerRandom:
    """cVoid+10C LCG; Sim supplies an explicit engineering seed."""
    state: int

    def between(self, low, high):
        low, high = f32(low), f32(high)
        self.state = (self.state * 69069 + 1) & 0xffffffff
        return f32(low + (high - low) * (self.state / 4294967296.))


@dataclass
class FlowerCycle:
    flower_type: int
    threshold: float
    edge: float
    duration: float
    timer: float = 0.
    phase: float = 0.
    previous_phase: float = 0.
    playing: bool = False
    completions: int = 0
    has_nectar_node: bool = True

    @classmethod
    def initial(cls, flower_type, rng, *, multiplayer=False, rescue=False):
        threshold, edge, duration = NORMAL_TRACKS.get(flower_type, (30., 0., 0.))
        if multiplayer:
            threshold = f32(threshold * .5)
        return cls(flower_type, threshold, edge, duration,
                   timer=rng.between(threshold * .5, threshold),
                   has_nectar_node=flower_type in NORMAL_TRACKS and not rescue)

    def update(self, arg2, *, occupied, nectar_count, rng,
               level_present=True, inhibited=False, rescue=False):
        """Return a birth edge; parent detects/cache first, then child advances.

        Missing node consumes the edge without allocating. Pickup does not
        restart the timer. Count40 only gates occupied non-type2 restarts.
        """
        dt = f32(arg2)
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('flower arg2 must be finite and nonnegative')
        spawn = False
        if dt:
            if level_present and not inhibited and not rescue:
                self.timer = f32(self.timer + dt)
                if (self.timer > self.threshold
                        and (not occupied or (self.flower_type != 2 and nectar_count < 40))):
                    self.timer = rng.between(0., self.threshold * .5)
                    self.phase = 0.
                    self.playing = self.duration > 0
                    self.completions = 0  # 451A50 resets track+1C, not flower+194.
                spawn = (self.flower_type in NORMAL_TRACKS and self.has_nectar_node
                         and self.previous_phase < self.edge <= self.phase)
            self.previous_phase = self.phase
        if self.playing:
            self.phase = f32(self.phase + dt)  # speed1; 44D110 final float store.
            # 44D13B tests C0|C3: equality returns, strict greater stops.
            if self.phase > self.duration:
                self.completions += 1
                self.playing = False         # no clamp to last-key time.
        return spawn

    def snapshot(self):
        return {'scope': 'normal-flower-animation-edge-f32-v1',
                'type': self.flower_type, 'threshold': self.threshold,
                'edge': self.edge, 'duration': self.duration, 'timer': self.timer,
                'phase': self.phase, 'previousPhase': self.previous_phase,
                'playing': self.playing, 'completions': self.completions,
                'hasNectarNode': self.has_nectar_node}
