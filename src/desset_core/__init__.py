"""Experimental algorithms for DESSET; no operational integrations."""

from .dispatch import Assignment, Courier, DispatchResult, Order, dispatch
from .fleet import FleetPlan, FleetVehicle, VehicleAssignment, optimize_fleet
from .fleet_repair import optimize_fleet_repaired
from .fleet_heuristic import optimize_fleet_adaptive, optimize_fleet_insertion
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
    "FleetPlan",
    "FleetVehicle",
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
    "VehicleAssignment",
    "dispatch",
    "fetch_local_osrm_table",
    "optimize_fleet",
    "optimize_fleet_adaptive",
    "optimize_fleet_insertion",
    "optimize_fleet_repaired",
    "optimize_multistop",
    "parse_osrm_table",
]
