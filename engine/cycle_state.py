"""Persist cycle decisions per monitoring without changing existing history."""
from engine.cycle_rules import CycleSnapshot
from data.models import PriceCycleState


def read_snapshot(row: PriceCycleState) -> CycleSnapshot:
    return CycleSnapshot(**{key: getattr(row, key) for key in CycleSnapshot.__dataclass_fields__})


def write_snapshot(row: PriceCycleState, snapshot: CycleSnapshot) -> None:
    for key in CycleSnapshot.__dataclass_fields__:
        setattr(row, key, getattr(snapshot, key))
