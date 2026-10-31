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


def test_link_quality_and_stats_optional_flags() -> None:
    from contract.contract import LinkQuality

    link = LinkQuality(peerId="b", link="wifi", rttMs=1, mbps=10, lossPct=100, ts=1, online=False)
    assert link.model_dump()["online"] is False and "simulated" not in link.model_dump()
    assert (
        "online" not in LinkQuality(peerId="b", link="wifi", rttMs=1, mbps=10, lossPct=0, ts=1).model_dump()
    )
    stale = Stats(
        deviceId="a",
        ts=1,
        cpuPct=1,
        memPct=1,
        memFreeMb=1,
        diskFreeMb=1,
        battery=None,
        online=False,
        stale=True,
    )
    assert stale.model_dump()["stale"] is True
