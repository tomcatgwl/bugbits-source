"""Per-nectar original float fields; independent of presentation frame rate.

R366 original ceNectar uses arg1, not global world time. Float32 stores are
modeled explicitly; this is not a claim of complete x87/CRT equivalence.
"""
from dataclasses import dataclass
import math
import struct


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


@dataclass
class WorldClock:
    """cGameWorld normal/low-accumulator dispatch, not the entire pause machine."""
    step: float = f32(.01)
    accumulator: float = 0.0
    dispatch_count: int = 0

    def advance(self, arg1, arg2, *, eligible=True, low_enabled=True):
        if (not math.isfinite(self.step) or self.step <= 0
                or not math.isfinite(self.accumulator) or self.accumulator < 0
                or any(not math.isfinite(v) or v < 0 for v in (arg1, arg2))):
            raise ValueError('invalid world clock')
        self.accumulator = f32(self.accumulator + f32(arg1))
        arg2 = f32(arg2)
        calls = []
        if self.accumulator < self.step:
            if low_enabled:
                calls.append((0.0, arg2))
        else:
            while self.accumulator >= self.step:
                if eligible:
                    calls.append((self.step, arg2))
                    arg2 = 0.0  # AFTER the complete child traversal, not each child.
                self.accumulator = f32(self.accumulator - self.step)
        self.dispatch_count += len(calls)
        return tuple(calls)

    def snapshot(self):
        return {'scope': 'world-substep-default-f32-v1', 'step': self.step,
                'accumulator': self.accumulator, 'dispatchCount': self.dispatch_count}


@dataclass
class FlightWaypoint:
    """Original candidate/chain offsets; adapter owns chain classification."""
    name: str
    pos: tuple
    water: bool = False
    links154: tuple = ()
    links130: tuple = ()


@dataclass
class NectarState:
    entity_id: int
    pos: tuple
    born_tick: int
    size: float = 0.0
    target_size: float = 5.0
    core_angle: float = 0.0
    glow_angle: float = 0.0
    flower_index: int = None
    carrier_id: int = None
    waypoint: str = None
    alive: bool = True
    rng_state: int = 0
    flight_start: tuple = None
    flight_target: tuple = None
    flight_elapsed: float = 0.0
    flight_duration: float = 0.0
    instance_name: str = 'nectar'
    classification_member: bool = True
    delete_requested: bool = False
    delete_ready: bool = False
    destroyed: bool = False

    def set_position(self, point):
        """49BAA0 finite slot20: copy position and endpoints, retain clocks.

        This does not cancel or restart an active flight. Its next update can
        still add the original arc to the newly equal endpoints.
        """
        value=tuple(f32(v) for v in point)
        if len(value)!=3 or any(not math.isfinite(v) for v in value):
            raise ValueError('nectar position requires three finite components')
        self.pos=value
        self.flight_start=value
        self.flight_target=value

    def request_delete(self):
        """Original +12B marker; membership and self fields remain until sweep."""
        if self.destroyed:
            raise ValueError('cannot request a destroyed nectar')
        self.delete_requested=True

    def finish_update(self,arg2):
        """442EC0 runs AFTER nectar's fields; only positive arg2 arms +12C."""
        value=f32(arg2)
        if not math.isfinite(value) or value<0:
            raise ValueError('nectar arg2 must be finite and nonnegative')
        if not self.destroyed and self.delete_requested and value>0:
            self.delete_ready=True

    def destroy(self):
        """World removal already happened; base destructor unregisters class."""
        if not self.delete_ready or not self.delete_requested or self.destroyed:
            raise ValueError('nectar not ready for actual destruction')
        self.classification_member=False
        self.destroyed=True
        self.alive=False

    def _random(self):
        self.rng_state = (self.rng_state * 69069 + 1) & 0xffffffff
        return self.rng_state

    def redirect(self, candidates, nodes=None):
        """49BB20 selection: qualified countdown, budget, water and chain fallback.

        Failure preserves flight/position/waypoint (but may consume initial RNG).
        Runtime GetTickCount seeding and adapter chain mapping are separate.
        """
        if not candidates:
            return False
        if any(not isinstance(w, FlightWaypoint) for w in candidates):
            raise ValueError('nectar redirect requires non-null waypoint records')
        nodes = nodes if nodes is not None else {w.name: w for w in candidates}
        remaining = ((self._random() >> 1) % len(candidates) + 1
                     if len(candidates) > 1 else 1)
        chosen = None
        for index in range(5000):
            budget = 4999 - index
            candidate = candidates[index % len(candidates)]
            if candidate.water:
                continue
            if math.dist(self.pos, candidate.pos) < 100 and budget >= 500:
                continue
            remaining -= 1
            if remaining == 0:
                chosen = candidate
                break
        if chosen is None:
            return False
        links = chosen.links154 if (self._random() >> 1) % 100 < 50 else chosen.links130
        neighbor = None
        if links:
            at = (self._random() >> 1) % len(links) if len(links) > 1 else 0
            neighbor = nodes.get(links[at])
        target = tuple(chosen.pos)
        destination = chosen.name
        if neighbor is not None and not neighbor.water:
            t = f32(self._random() / 4294967296.0)
            target = tuple(f32(f32(a * f32(1 - t)) + f32(b * t))
                           for a, b in zip(chosen.pos, neighbor.pos))
            if t >= .5:
                destination = neighbor.name
        target = (target[0], f32(target[1] + 2.5), target[2])
        self.start_flight(target, waypoint=destination)
        return True

    def start_flight(self, target, *, waypoint):
        self.waypoint = waypoint
        self.flight_start = tuple(self.pos)
        self.flight_target = tuple(f32(v) for v in target)
        self.flight_elapsed = 0.0
        self.flight_duration = 2.0

    def update(self, dt):
        dt = f32(dt)
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('nectar dt must be finite and nonnegative')
        if self.destroyed:
            return
        self.size = f32(self.size + (self.target_size - self.size) * dt * 2)
        self.core_angle = f32(self.core_angle + f32(3.1415927410125732 * dt))
        self.glow_angle = f32(self.glow_angle - f32(1.5707963705062866 * dt))
        # Pickup does NOT clear the flight clocks. Traversal precedence remains
        # an explicit integration concern; this consumer must not cancel flight.
        if self.flight_duration > 0:
            self.flight_elapsed = f32(self.flight_elapsed + dt)
            if self.flight_elapsed > self.flight_duration:
                self.pos = self.flight_target
                self.flight_elapsed = self.flight_duration = 0.0
            else:
                t = f32(self.flight_elapsed / self.flight_duration)
                arc = f32(200 * t * (1 - t))  # 49C277, before storing 1-t.
                complement = f32(1 - t)       # 49C2A1.
                linear = tuple(f32(f32(a * complement) + f32(b * t))
                               for a, b in zip(self.flight_start, self.flight_target))
                self.pos = (linear[0], f32(linear[1] + arc), linear[2])

    def snapshot(self):
        return {'scope': 'nectar-fields-f32-v1', 'id': self.entity_id,
                'instanceName':self.instance_name,
                'lifecycle':{'scope':'nectar-delayed-classification-v1',
                             'classificationMember':self.classification_member,
                             'deleteRequested':self.delete_requested,
                             'deleteReady':self.delete_ready,'destroyed':self.destroyed},
                'bornTick': self.born_tick, 'positionYup': list(self.pos),
                'size': self.size, 'targetSize': self.target_size,
                'coreAngle': self.core_angle, 'glowAngle': self.glow_angle,
                'glowSize': f32(self.size * (1.5 + .5 * f32(math.sin(self.glow_angle)))),
                'flowerIndex': self.flower_index, 'carrierId': self.carrier_id,
                'waypoint': self.waypoint, 'alive': self.alive, 'rngState': self.rng_state,
                'flight': {'start': list(self.flight_start) if self.flight_start is not None else None,
                           'target': list(self.flight_target) if self.flight_target is not None else None,
                           'elapsed': self.flight_elapsed, 'duration': self.flight_duration}}
