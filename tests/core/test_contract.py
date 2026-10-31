from __future__ import annotations

from contract.contract import (
    Battery,
    BusEventAdapter,
    MigValidated,
    PeerMessageAdapter,
    Stats,
    StatsUpdateEvent,
)


def test_optional_fields_are_omitted_and_nullable_kept() -> None:
    stats = Stats(
        deviceId="a", ts=1, cpuPct=1, memPct=1, memFreeMb=1, diskFreeMb=1, battery=None, online=True
    )
    dumped = stats.model_dump()
    assert "simulated" not in dumped
    assert dumped["battery"] is None


def test_discriminated_unions_roundtrip() -> None:
    msg = PeerMessageAdapter.validate_json('{"t": "mig.validated", "migrationId": "m", "ok": true}')
    assert isinstance(msg, MigValidated)
    ev = StatsUpdateEvent(
        stats=Stats(
            deviceId="a",
            ts=1,
            cpuPct=1,
            memPct=1,
            memFreeMb=1,
            diskFreeMb=1,
            battery=Battery(pct=50, charging=False),
            online=True,
        )
    )
    assert BusEventAdapter.validate_json(ev.model_dump_json()) == ev
