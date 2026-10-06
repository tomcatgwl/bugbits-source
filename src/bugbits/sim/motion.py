"""Finite normal ceActive/physics stages on the engineering 20Hz clock.

R389/R390: force is mass-scaled acceleration, the cap applies to OLD velocity,
and position advances before momentum integration. This is not an x87 emulator
or an assertion of original asynchronous birth/render/collision scheduling.
"""
from dataclasses import dataclass
import math

from bugbits.sim.nectar import f32


def length(vector):
    return math.sqrt(f32(sum(v * v for v in vector)))


def normalize(vector):
    size = f32(length(vector))
    if size == 0:
        return vector
    reciprocal = f32(1 / size)
    return tuple(f32(v * reciprocal) for v in vector)


@dataclass
class NormalMotion:
    position: tuple
    direction: tuple
    mass: float
    acceleration: float
    direction_factor: float
    body_position: tuple = None
    control_direction: tuple = None
    velocity: tuple = (0.,0.,0.)
    momentum: tuple = (0.,0.,0.)
    force: tuple = (0.,0.,0.)
    max_speed: float = 0.
    controller_state: int = 1

    def __post_init__(self):
        self.position = tuple(f32(v) for v in self.position)
        self.direction = normalize(tuple(f32(v) for v in self.direction))
        self.body_position = self.position
        self.control_direction = self.direction
        self.mass, self.acceleration, self.direction_factor = map(
            f32, (self.mass, self.acceleration, self.direction_factor))

    def point_at(self, target):
        self.control_direction = normalize(tuple(f32(b-a)
                                                for a,b in zip(self.position,target)))

    def advance(self, dt):
        dt = f32(dt)
        weight = min(1., f32(dt * self.direction_factor))
        complement = f32(1 - weight)
        mixed = tuple(f32(f32(v * complement) + f32(t * weight))
                      for v,t in zip(self.direction,self.control_direction))
        # Original raw C is minus canonical Y. Clamp branches normalize
        # before calling the body setter; an unclamped vector skips this
        # first normalize.
        clamped = abs(mixed[1]) > .25
        mixed = (mixed[0], min(.25,max(-.25,mixed[1])), mixed[2])
        if clamped:
            mixed = normalize(mixed)
        if mixed == (0.,0.,0.):
            # 443090 substitutes raw(0,1,0) for a zero body direction.
            # loaded-yup-v1 maps that direction to canonical(-1,0,0).
            mixed = (-1.,0.,0.)
        # 443090 normalizes its input; 405560 normalizes the forward vector
        # again before storing the body matrix consumed by442E00 (roll0).
        self.direction = normalize(normalize(mixed))
        acceleration = tuple(f32(v * self.acceleration) for v in self.direction)
        self.force = tuple(f32(old + self.mass * a)
                           for old,a in zip(self.force,acceleration))
        if length(self.velocity) > self.max_speed:
            # 401350 stores cap/sqrt(sumSquares) directly; normalizing first
            # inserts extra f32 stores and can change the capped velocity.
            scale = f32(self.max_speed / length(self.velocity))
            self.velocity = tuple(f32(v * scale) for v in self.velocity)
            self.momentum = tuple(f32(v * self.mass) for v in self.velocity)
        self.position = tuple(f32(p + f32(v * dt))
                              for p,v in zip(self.position,self.velocity))
        self.body_position = self.position
        damping = f32(max(0., 1 - dt))
        self.momentum = tuple(f32(f32(p * damping) + f32(force * dt))
                              for p,force in zip(self.momentum,self.force))
        self.force = (0.,0.,0.)
        if self.mass > 0:
            reciprocal_mass = f32(1 / self.mass)
            self.velocity = tuple(f32(p * reciprocal_mass) for p in self.momentum)

    def follow_route_height(self, current, target, dt):
        line = normalize(tuple(f32(b-a) for a,b in zip(current,target)))
        offset = tuple(f32(p-a) for p,a in zip(self.position,current))
        projection = f32(sum(p * d for p,d in zip(offset,line)))
        # 4AF022 mask41 includes equality; only strictly positive projection
        # takes the projected-height branch. Zero uses the slower CC anchor.
        if projection > 0:
            goal = f32(current[1] + f32(line[1] * projection))
            delta = (goal - self.position[1]) * f32(dt) * 2
        else:
            delta = (current[1] - self.position[1]) * f32(dt) * .5
        self.position = (self.position[0],f32(self.position[1] + delta),self.position[2])

    def snapshot(self):
        return {'scope':'normal-active-physics-f32-20hz-v1',
                'initializationScope':'constructor-zero-sync-activation-unverified-v1',
                'position':list(self.position),'bodyPosition':list(self.body_position),
                'direction':list(self.direction),'controlDirection':list(self.control_direction),
                'velocity':list(self.velocity),'momentum':list(self.momentum),
                'force':list(self.force),'maxSpeed':self.max_speed,
                'controllerState':self.controller_state,
                'mass':self.mass,'acceleration':self.acceleration,
                'directionFactor':self.direction_factor}
