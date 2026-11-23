"""Deterministic, single-wave courier-to-order matching.

Inputs are supplied estimates, NOT observed travel times or real DESSET orders.
Each courier can receive at most one order per dispatch call. No external I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

ALGORITHM_VERSION = "dispatch-mincost-v0.1"


@dataclass(frozen=True)
class Courier:
    id: str
    capacity_units: int
    available: bool = True


@dataclass(frozen=True)
class Order:
    id: str
    load_units: int
    max_pickup_seconds: int | None = None


@dataclass(frozen=True)
class Assignment:
    courier_id: str
    order_id: str
    estimated_pickup_seconds: int


@dataclass(frozen=True)
class Unassigned:
    order_id: str
    reason: str


@dataclass(frozen=True)
class DispatchResult:
    strategy: str
    assignments: tuple[Assignment, ...]
    unassigned: tuple[Unassigned, ...]
    total_estimated_pickup_seconds: int


@dataclass
class _Edge:
    to: int
    reverse_index: int
    capacity: int
    cost: int


def _is_nonnegative_integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _validate(
    couriers: Sequence[Courier],
    orders: Sequence[Order],
    pickup_seconds: Mapping[tuple[str, str], int],
) -> None:
    courier_ids: set[str] = set()
    order_ids: set[str] = set()
    for courier in couriers:
        if not isinstance(courier.id, str) or not courier.id.strip():
            raise ValueError("courier id must be a nonempty string")
        if courier.id in courier_ids:
            raise ValueError("duplicate courier id")
        courier_ids.add(courier.id)
        if not _is_nonnegative_integer(courier.capacity_units):
            raise ValueError("capacity_units must be a nonnegative integer")
        if type(courier.available) is not bool:
            raise ValueError("available must be boolean")
    for order in orders:
        if not isinstance(order.id, str) or not order.id.strip():
            raise ValueError("order id must be a nonempty string")
        if order.id in order_ids:
            raise ValueError("duplicate order id")
        order_ids.add(order.id)
        if not _is_nonnegative_integer(order.load_units) or order.load_units == 0:
            raise ValueError("load_units must be a positive integer")
        if order.max_pickup_seconds is not None and not _is_nonnegative_integer(
            order.max_pickup_seconds
        ):
            raise ValueError("max_pickup_seconds must be a nonnegative integer or null")
    for pair, seconds in pickup_seconds.items():
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or pair[0] not in courier_ids
            or pair[1] not in order_ids
        ):
            raise ValueError("matrix contains unknown or malformed courier/order pair")
        if not _is_nonnegative_integer(seconds):
            raise ValueError("pickup_seconds values must be nonnegative integers")


def _eligible_pairs(
    couriers: Sequence[Courier],
    orders: Sequence[Order],
    pickup_seconds: Mapping[tuple[str, str], int],
) -> dict[tuple[str, str], int]:
    eligible = {}
    for courier in couriers:
        for order in orders:
            seconds = pickup_seconds.get((courier.id, order.id))
            if (
                courier.available
                and courier.capacity_units >= order.load_units
                and seconds is not None
                and (order.max_pickup_seconds is None or seconds <= order.max_pickup_seconds)
            ):
                eligible[(courier.id, order.id)] = seconds
    return eligible


def _baseline_greedy(
    couriers: Sequence[Courier],
    orders: Sequence[Order],
    eligible: Mapping[tuple[str, str], int],
) -> list[Assignment]:
    remaining = {courier.id for courier in couriers}
    assignments = []
    for order in orders:
        candidates = sorted(
            (seconds, courier_id)
            for (courier_id, order_id), seconds in eligible.items()
            if order_id == order.id and courier_id in remaining
        )
        if candidates:
            seconds, courier_id = candidates[0]
            assignments.append(Assignment(courier_id, order.id, seconds))
            remaining.remove(courier_id)
    return assignments


def _min_cost_max_matching(
    couriers: Sequence[Courier],
    orders: Sequence[Order],
    eligible: Mapping[tuple[str, str], int],
) -> list[Assignment]:
    """Exact maximum-cardinality, then minimum-total-cost matching (Bellman-Ford flow)."""
    n_couriers, n_orders = len(couriers), len(orders)
    source = 0
    courier_start = 1
    order_start = courier_start + n_couriers
    sink = order_start + n_orders
    graph: list[list[_Edge]] = [[] for _ in range(sink + 1)]

    def add_edge(start: int, end: int, cost: int) -> _Edge:
        forward = _Edge(end, len(graph[end]), 1, cost)
        backward = _Edge(start, len(graph[start]), 0, -cost)
        graph[start].append(forward)
        graph[end].append(backward)
        return forward

    for courier_index in range(n_couriers):
        add_edge(source, courier_start + courier_index, 0)
    for order_index in range(n_orders):
        add_edge(order_start + order_index, sink, 0)

    references: dict[tuple[str, str], _Edge] = {}
    for courier_index, courier in enumerate(couriers):
        for order_index, order in enumerate(orders):
            pair = (courier.id, order.id)
            if pair in eligible:
                references[pair] = add_edge(
                    courier_start + courier_index,
                    order_start + order_index,
                    eligible[pair],
                )

    # Augment until no feasible path remains: maximize count before minimizing cost.
    while True:
        distances: list[int | None] = [None] * len(graph)
        previous: list[tuple[int, int] | None] = [None] * len(graph)
        distances[source] = 0
        for _ in range(len(graph) - 1):
            changed = False
            for node, edges in enumerate(graph):
                if distances[node] is None:
                    continue
                for edge_index, edge in enumerate(edges):
                    if edge.capacity == 0:
                        continue
                    candidate = distances[node] + edge.cost
                    if distances[edge.to] is None or candidate < distances[edge.to]:
                        distances[edge.to] = candidate
                        previous[edge.to] = (node, edge_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            step = previous[node]
            assert step is not None  # reachable nodes have predecessors
            parent, edge_index = step
            edge = graph[parent][edge_index]
            edge.capacity -= 1
            graph[node][edge.reverse_index].capacity += 1
            node = parent

    return [
        Assignment(courier_id, order_id, eligible[(courier_id, order_id)])
        for (courier_id, order_id), edge in references.items()
        if edge.capacity == 0
    ]


def dispatch(
    couriers: Sequence[Courier],
    orders: Sequence[Order],
    pickup_seconds: Mapping[tuple[str, str], int],
    *,
    strategy: str = "optimal",
) -> DispatchResult:
    """Assign one order per available courier with caller-supplied pickup estimates.

    An omitted matrix entry is infeasible. The result is not a real-world ETA,
    travel route, price, margin, or guaranteed service-level prediction.
    """
    if strategy not in ("optimal", "greedy"):
        raise ValueError("strategy must be optimal or greedy")
    _validate(couriers, orders, pickup_seconds)
    couriers_sorted = sorted(couriers, key=lambda item: item.id)
    orders_sorted = sorted(orders, key=lambda item: item.id)
    eligible = _eligible_pairs(couriers_sorted, orders_sorted, pickup_seconds)
    if strategy == "optimal":
        assigned = _min_cost_max_matching(couriers_sorted, orders_sorted, eligible)
    else:
        assigned = _baseline_greedy(couriers_sorted, orders_sorted, eligible)
    assigned.sort(key=lambda item: (item.order_id, item.courier_id))
    assigned_ids = {assignment.order_id for assignment in assigned}
    unassigned = []
    for order in orders_sorted:
        if order.id not in assigned_ids:
            reason = (
                "no_eligible_courier_or_estimate"
                if not any(order_id == order.id for (_, order_id) in eligible)
                else "courier_capacity_conflict"
            )
            unassigned.append(Unassigned(order.id, reason))
    return DispatchResult(
        strategy=f"{ALGORITHM_VERSION}:{strategy}",
        assignments=tuple(assigned),
        unassigned=tuple(unassigned),
        total_estimated_pickup_seconds=sum(item.estimated_pickup_seconds for item in assigned),
    )
