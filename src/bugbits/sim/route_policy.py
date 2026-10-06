"""Normal directed local route selection, from 4A4B70/4A5660.

Consumes explicit ordered Bugs/Nectars records. Their scene lifetime/order and
the Sim's 20Hz motion adapter are separate from this finite F32 score contract.
Original DATA graphs are DAGs; runtime cyclic mutation is unsupported here.
"""
from bugbits.sim.nectar import f32

ALPHA = 0.20000000298023224


class DirectedRoutePolicy:
    def __init__(self, world):
        self.outgoing, self.incoming = world.directed_links()
        nodes = world.starts + world.waypoints
        self.water = {n.name: bool(getattr(n, 'water', False)) for n in nodes}
        # Explicit injected adjacency-only fixtures retain their engineering
        # semantics. Actual parsed worlds, including isolated nodes, use links.
        self.declared = world.world_id is not None or any(n.connect_to for n in nodes)

    def links(self, bug, is_reversed):
        incoming = bool(bug.side) ^ bool(bug.route_returning) ^ bool(is_reversed)
        return self.incoming if incoming else self.outgoing

    def choose(self, bug, peers, nectars, is_reversed, *, first_only=False):
        links = self.links(bug, is_reversed)
        candidates = links.get(bug.route_current, ())
        if not candidates:
            return None
        if first_only or len(candidates) == 1:
            return candidates[0]
        best = candidates[0]
        score = self._score(best, links, bug, peers, nectars, frozenset())
        for candidate in candidates[1:]:
            value = self._score(candidate, links, bug, peers, nectars, frozenset())
            if value > score:  # Equal or unordered preserves original first.
                best, score = candidate, value
        return best

    def _score(self, node, links, bug, peers, nectars, ancestors):
        score, depth, first = f32(0.), 1, True
        visited = set(ancestors)
        while True:
            if node not in links or node in visited:
                raise ValueError('unsupported cyclic or null original score input')
            visited.add(node)
            following = links[node]
            if not first and len(following) != 1:
                if not bug.can_gather or score != 0.:
                    return score
                if len(following) > 1:
                    for child in following:
                        score = f32(score + self._score(child, links, bug, peers, nectars,
                                                       frozenset(visited)))
                return score
            if self.water[node]:
                score = f32(score + (500. if bug.unit_name in
                            ('waterbeetle', 'giantwaterbeetle') else -500.))
            denominator = ALPHA * depth + 1.
            for peer in peers:
                if peer is bug or peer.route_current != node:
                    continue
                if peer.side == bug.side:
                    contribution = 5. if peer.trapped and not bug.can_gather else -1. / denominator
                elif bug.carried_nectar_id is not None:
                    contribution = -2. / denominator
                else:
                    contribution = 2. / denominator
                score = f32(score + contribution)
            for nectar in nectars:
                if not nectar.classification_member or nectar.waypoint != node:
                    continue
                if bug.can_gather:
                    if bug.carried_nectar_id is not None:
                        continue
                    contribution = 10. / denominator
                else:
                    contribution = .5 / denominator
                score = f32(score + contribution)
            if not following:
                # The original first-pass fallthrough has no null-next guard.
                # Actual nine-world fork candidates all have successors.
                raise ValueError('unsupported terminal first-pass score input')
            node = following[0]
            first, depth = False, depth + 1
