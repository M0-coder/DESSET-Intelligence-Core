"""Experimental algorithms for DESSET; no operational integrations."""

from .dispatch import Assignment, Courier, DispatchResult, Order, dispatch
from .multistop import (
    DeliveryJob,
    MultiStopPlan,
    NoFeasibleRouteError,
    RouteInputError,
    RouteVisit,
    optimize_multistop,
)
from .osrm_local import LocalRoadMatrix, RoadPoint, fetch_local_osrm_table
from .routing_matrix import (
    MatrixInputError,
    MatrixProvenance,
    PickupMatrix,
    parse_osrm_table,
)

__all__ = [
    "Assignment",
    "Courier",
    "DeliveryJob",
    "DispatchResult",
    "LocalRoadMatrix",
    "MatrixInputError",
    "MatrixProvenance",
    "MultiStopPlan",
    "NoFeasibleRouteError",
    "Order",
    "PickupMatrix",
    "RoadPoint",
    "RouteInputError",
    "RouteVisit",
    "dispatch",
    "fetch_local_osrm_table",
    "optimize_multistop",
    "parse_osrm_table",
]
