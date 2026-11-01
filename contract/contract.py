"""Python mirror of contract/contract.ts. SOURCE OF TRUTH is the .ts file; changes only via P1.

Field names are camelCase and identical to the TypeScript contract. Optional TS fields (`x?: T`)
default to None and are omitted when serialized; nullable TS fields (`x: T | null`) are required
and serialize as null.

Module interfaces are typing.Protocols. Every service has async startup()/shutdown() lifecycle hooks that
the app factory calls; do not touch other services inside create_*(ctx), only from startup() on.
"""

from __future__ import annotations

import builtins
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    model_serializer,
)

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

Arch = Literal["x86_64", "arm64"]
OsName = Literal["windows", "linux", "macos"]
LinkType = Literal["wifi", "cable", "loopback"]
Decision = Literal["MIGRATE", "REMOTE_ACCESS", "STAY"]
Trigger = Literal[
    "low_battery", "cpu_pressure", "memory_pressure", "connectivity_lost", "predicted", "user_command"
]
AuthorityState = Literal["SOURCE", "FENCED", "TARGET"]
RunState = Literal["idle", "running", "paused", "stopped", "exited"]
Phase = Literal[
    "IDLE",
    "CONNECTING",
    "EVALUATING",
    "TRANSFERRING",
    "VALIDATING",
    "FENCING",
    "STARTING_TARGET",
    "COMPLETED",
    "ROLLING_BACK",
    "ROLLED_BACK",
    "REMOTE_ACCESS",
    "FAILED",
]
Severity = Literal["pass", "warn", "block"]


class ContractModel(BaseModel):
    """Base for all contract models: drops optional (`?`) fields that are None when serializing."""

    model_config = ConfigDict(extra="ignore")

    @model_serializer(mode="wrap")
    def _omit_unset_optionals(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for name, field in type(self).model_fields.items():
            if not field.is_required() and name in data and data[name] is None:
                del data[name]
        return data


# ---------------------------------------------------------------- data models


class DeviceAddr(ContractModel):
    addr: str
    link: LinkType


class DeviceInfo(ContractModel):
    id: str
    name: str
    os: OsName
    arch: Arch
    cpuCores: int
    ramMb: int
    gpu: str | None
    diskFreeMb: int
    runtimes: dict[str, str]
    libs: list[str]
    addrs: list[DeviceAddr]
    agentVersion: str
    simulated: bool | None = None


class Battery(ContractModel):
    pct: float
    charging: bool


class Stats(ContractModel):
    deviceId: str
    ts: float
    cpuPct: float
    memPct: float
    memFreeMb: int
    diskFreeMb: int
    battery: Battery | None
    online: bool
    simulated: bool | None = None
    stale: bool | None = None  # no fresh sample from this device for a while (last values kept)


class LinkQuality(ContractModel):
    peerId: str
    link: LinkType
    rttMs: float
    mbps: float
    lossPct: float
    ts: float
    online: bool | None = None  # False while the peer is unreachable
    simulated: bool | None = None  # values come from fault injection or a simulator


class CheckpointDef(ContractModel):
    id: str
    name: str
    paths: list[str]


class RuntimeReq(ContractModel):
    name: str
    minVersion: str


class WorkloadManifest(ContractModel):
    id: str
    name: str
    command: str
    runtime: RuntimeReq
    arch: list[Arch]
    os: list[OsName]
    minRamMb: int
    minCpuCores: int
    minDiskMb: int
    needsGpu: bool
    libs: list[str]
    checkpoints: list[CheckpointDef]
    remoteCapable: bool


class CheckpointRecord(ContractModel):
    id: str
    seq: int
    sizeBytes: int
    sha256: str
    createdAt: float
    sent: bool | None = None
    validated: bool | None = None


class Reason(ContractModel):
    code: str
    severity: Severity
    text: str


class FeasibilityResult(ContractModel):
    workloadId: str
    sourceId: str
    targetId: str
    decision: Decision
    reasons: list[Reason]
    estTransferSec: float
    estInterruptionMs: float
    ts: float


class Authority(ContractModel):
    workloadId: str
    holder: str | None
    epoch: int
    state: AuthorityState
    migrationId: str | None = None  # the migration that set this lease; None if never migrated


class CheckpointMetric(ContractModel):
    id: str
    stage: Literal["initial", "catchup", "delta", "precopy"]
    sizeBytes: int
    chunks: int
    retries: int
    transferMs: float
    mbps: float
    skipped: bool


class CutoverTiming(ContractModel):
    """Where the interruption (pause to mig.started ok) went."""

    catchupRounds: int  # live delta rounds before freezing
    fenceMs: float  # pause + fence + final checkpoint of manifest paths
    deltaBytes: int  # sent while frozen
    deltaMs: float  # frozen delta transfer + validation
    startMs: float  # mig.start until mig.started ok (target restore + launch)


class MigrationMetrics(ContractModel):
    migrationId: str
    link: LinkType
    chunkSize: int
    durationMs: float
    interruptionMs: float | None = None
    bytesTotal: int
    bytesDone: int
    bytesSkipped: int
    throughputMbps: float
    checkpoints: list[CheckpointMetric]
    ts: float
    cutover: CutoverTiming | None = None


class AuthorityConflict(ContractModel):
    workloadId: str
    deviceId: str
    peerId: str
    localEpoch: int
    remoteEpoch: int
    winner: str
    stopped: str
    reason: str
    ts: float


class MigrationStatus(ContractModel):
    id: str
    workloadId: str
    sourceId: str
    targetId: str
    phase: Phase
    trigger: Trigger
    link: LinkType
    decision: Decision | None = None
    reasons: list[Reason]
    checkpoints: list[CheckpointRecord]
    bytesTotal: int
    bytesDone: int
    authority: Authority
    interruptionMs: float | None = None
    error: str | None = None
    startedAt: float
    endedAt: float | None = None
    metrics: MigrationMetrics | None = None


class Recommendation(ContractModel):
    workloadId: str
    trigger: Trigger
    targetId: str | None
    decision: Decision
    reasons: list[Reason]
    auto: bool
    ts: float


class RemoteSession(ContractModel):
    id: str
    workloadId: str
    hostId: str
    viewerId: str
    consent: bool
    fps: float
    ts: float


class WorkloadRun(ContractModel):
    workloadId: str
    state: RunState
    pid: int | None
    exitCode: int | None
    startedAt: float | None
    restored: list[str]
    logTail: list[str]


class DecisionLog(ContractModel):
    id: str
    ts: float
    workloadId: str
    trigger: Trigger
    decision: Decision
    reasons: list[Reason]
    migrationId: str | None = None


# ---------------------------------------------------------------- peer link messages


class PeerHello(ContractModel):
    t: Literal["peer.hello"] = "peer.hello"
    device: DeviceInfo


class PeerStats(ContractModel):
    t: Literal["peer.stats"] = "peer.stats"
    stats: Stats


class PeerPing(ContractModel):
    t: Literal["peer.ping"] = "peer.ping"
    n: int


class PeerPong(ContractModel):
    t: Literal["peer.pong"] = "peer.pong"
    n: int


class MigPrepare(ContractModel):
    t: Literal["mig.prepare"] = "mig.prepare"
    migrationId: str
    manifest: WorkloadManifest
    checkpoints: list[CheckpointRecord]
    epoch: int
    signature: str
    chunkSize: int | None = None
    precopy: bool | None = None


class MigReady(ContractModel):
    t: Literal["mig.ready"] = "mig.ready"
    migrationId: str
    ok: bool
    reasons: list[Reason]
    have: list[str] | None = None


class MigChunk(ContractModel):
    t: Literal["mig.chunk"] = "mig.chunk"
    migrationId: str
    checkpointId: str
    index: int
    total: int
    dataB64: str
    sha256: str
    epoch: int


class MigChunkAck(ContractModel):
    t: Literal["mig.chunkAck"] = "mig.chunkAck"
    migrationId: str
    checkpointId: str
    index: int
    ok: bool


class MigValidated(ContractModel):
    t: Literal["mig.validated"] = "mig.validated"
    migrationId: str
    ok: bool
    failed: list[str] | None = None


class MigFence(ContractModel):
    t: Literal["mig.fence"] = "mig.fence"
    migrationId: str
    epoch: int


class MigFenced(ContractModel):
    t: Literal["mig.fenced"] = "mig.fenced"
    migrationId: str
    changed: list[CheckpointRecord]


class MigStart(ContractModel):
    t: Literal["mig.start"] = "mig.start"
    migrationId: str
    epoch: int


class MigStarted(ContractModel):
    t: Literal["mig.started"] = "mig.started"
    migrationId: str
    ok: bool
    error: str | None = None


class MigAbort(ContractModel):
    t: Literal["mig.abort"] = "mig.abort"
    migrationId: str
    reason: str


class AuthLeases(ContractModel):
    t: Literal["auth.leases"] = "auth.leases"
    leases: list[Authority]
    conflicts: list[AuthorityConflict] | None = None  # recently resolved, so both sides report them


PeerMessage = Annotated[
    (
        PeerHello
        | PeerStats
        | PeerPing
        | PeerPong
        | MigPrepare
        | MigReady
        | MigChunk
        | MigChunkAck
        | MigValidated
        | MigFence
        | MigFenced
        | MigStart
        | MigStarted
        | MigAbort
        | AuthLeases
    ),
    Field(discriminator="t"),
]
PeerMessageAdapter: TypeAdapter[PeerMessage] = TypeAdapter(PeerMessage)


# ---------------------------------------------------------------- bus events


class StatsUpdateEvent(ContractModel):
    t: Literal["stats.update"] = "stats.update"
    stats: Stats


class LinkUpdateEvent(ContractModel):
    t: Literal["link.update"] = "link.update"
    link: LinkQuality


class DevicePairedEvent(ContractModel):
    t: Literal["device.paired"] = "device.paired"
    device: DeviceInfo


class DeviceLostEvent(ContractModel):
    t: Literal["device.lost"] = "device.lost"
    deviceId: str


class RecommendationEvent(ContractModel):
    t: Literal["recommendation"] = "recommendation"
    rec: Recommendation


class DecisionLoggedEvent(ContractModel):
    t: Literal["decision.logged"] = "decision.logged"
    log: DecisionLog


class MigrationStatusEvent(ContractModel):
    t: Literal["migration.status"] = "migration.status"
    status: MigrationStatus


class AuthorityChangeEvent(ContractModel):
    t: Literal["authority.change"] = "authority.change"
    authority: Authority


class RemoteSessionEvent(ContractModel):
    t: Literal["remote.session"] = "remote.session"
    session: RemoteSession


class AuthorityConflictEvent(ContractModel):
    t: Literal["authority.conflict"] = "authority.conflict"
    conflict: AuthorityConflict


BusEvent = Annotated[
    (
        StatsUpdateEvent
        | LinkUpdateEvent
        | DevicePairedEvent
        | DeviceLostEvent
        | RecommendationEvent
        | DecisionLoggedEvent
        | MigrationStatusEvent
        | AuthorityChangeEvent
        | RemoteSessionEvent
        | AuthorityConflictEvent
    ),
    Field(discriminator="t"),
]
BusEventAdapter: TypeAdapter[BusEvent] = TypeAdapter(BusEvent)


# ---------------------------------------------------------------- module interfaces

PeerMessageHandler = Callable[[str, PeerMessage], Awaitable[None]]
"""Called with (fromDeviceId, message) for every decrypted message arriving on the peer link."""


@runtime_checkable
class Service(Protocol):
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...


@runtime_checkable
class DeviceService(Service, Protocol):
    """P2. Local device info plus the latest stats of every known device. Publishes stats.update."""

    def local_info(self) -> DeviceInfo: ...
    def list_devices(self) -> builtins.list[DeviceInfo]:
        """Local device first, then every known peer."""
        ...

    def latest_stats(self, device_id: str) -> Stats | None: ...
    def set_override(self, device_id: str, partial_stats: dict[str, Any] | None) -> None:
        """Dev simulator: merge partial Stats fields over real ones (marked simulated); None clears."""
        ...


@runtime_checkable
class PeerLink(Service, Protocol):
    """P2. Encrypted device-to-device link. Publishes link.update, device.paired, device.lost."""

    async def pair(self, addr: str, pin: str) -> DeviceInfo: ...
    async def connect(self, device_id: str) -> None: ...
    async def send(self, device_id: str, msg: PeerMessage) -> None: ...
    def on_message(self, handler: PeerMessageHandler) -> None: ...
    def link_quality(self, device_id: str) -> LinkQuality | None: ...
    def list_peers(self) -> builtins.list[DeviceInfo]: ...


@runtime_checkable
class SecureSession(Protocol):
    """P2. Ed25519 identity, X25519 + HKDF session key, AES-256-GCM, manifest signatures."""

    def identity_public_key(self) -> bytes: ...
    def ephemeral_public_key(self) -> bytes: ...
    def establish(self, peer_ephemeral_public_key: bytes, peer_identity_public_key: bytes) -> None: ...
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...
    def sign(self, data: bytes) -> str:
        """Base64 Ed25519 signature with this device's identity key."""
        ...

    def verify(self, data: bytes, signature: str, identity_public_key: bytes) -> bool: ...


@runtime_checkable
class FeasibilityEngine(Service, Protocol):
    """P3. One Reason per check; decision per the rules in docs/PROJECT_BRIEF.md. Budget < 500 ms."""

    async def evaluate(
        self,
        manifest: WorkloadManifest,
        source: DeviceInfo,
        target: DeviceInfo,
        link: LinkQuality | None,
    ) -> FeasibilityResult: ...


@runtime_checkable
class Orchestrator(Service, Protocol):
    """P3. Watches stats/link events, publishes recommendation, starts migrations in auto mode."""

    def recommendations(self) -> builtins.list[Recommendation]:
        """Latest recommendation per workload."""
        ...


@runtime_checkable
class HistoryStore(Service, Protocol):
    """P3. SQLite store under TELEPORT_HOME. log_decision publishes decision.logged.

    The dict-shaped results back P3's /api/history router (summaries, detail with timeline, export).
    """

    async def log_decision(self, log: DecisionLog) -> None: ...
    async def list_devices(self) -> builtins.list[DeviceInfo]: ...
    async def list_migrations(
        self,
        device: str | None = None,
        workload: str | None = None,
        decision: str | None = None,
        outcome: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[MigrationStatus]: ...
    async def list_decisions(
        self, limit: int = 100, offset: int = 0, workload: str | None = None
    ) -> builtins.list[DecisionLog]: ...
    async def list_device_summaries(self) -> builtins.list[dict[str, Any]]:
        """Every device ever seen: id, firstSeen, lastSeen, device (DeviceInfo), linkTypes, migrationCount."""
        ...

    async def get_device_detail(self, device_id: str) -> dict[str, Any] | None: ...
    async def get_migration(self, migration_id: str) -> dict[str, Any] | None: ...
    async def export_history(self) -> dict[str, Any]: ...


@runtime_checkable
class AuthorityService(Service, Protocol):
    """P1. One lease per workload, this device's view, persisted in TELEPORT_HOME/authority.json.

    Epochs only grow. Publishes authority.change on every transition.
    """

    def get(self, workload_id: str) -> Authority: ...
    def leases(self) -> builtins.list[Authority]:
        """Every lease this device knows (sent to peers for the split-brain check)."""
        ...

    async def adopt(self, lease: Authority) -> Authority:
        """Take a peer's view of a lease (after a handover or a lost conflict). Epochs never go down."""
        ...

    def may_run(self, workload_id: str) -> bool:
        """True only if this device holds the lease in state SOURCE or TARGET."""
        ...

    async def claim(self, workload_id: str, holder: str) -> Authority:
        """Become SOURCE for a workload started locally (epoch kept, 0 if new)."""
        ...

    async def fence(self, workload_id: str, migration_id: str | None = None) -> Authority:
        """SOURCE -> FENCED, epoch + 1, stamped with the migration that fences. Only the holder may fence."""
        ...

    async def grant(
        self, workload_id: str, holder: str, epoch: int, migration_id: str | None = None
    ) -> Authority:
        """Record `holder` as TARGET at `epoch` for `migration_id`. Raises if `epoch` is older than the
        current one, or if that epoch was issued by a different migration."""
        ...

    async def release(self, workload_id: str) -> Authority:
        """This device gives the lease up (holder None, epoch kept)."""
        ...

    async def rollback(self, workload_id: str, migration_id: str | None = None) -> Authority:
        """FENCED -> SOURCE, epoch + 1 so a target started at the fence epoch is now stale. Only the
        migration that fenced may roll back."""
        ...

    def check_epoch(self, workload_id: str, epoch: int) -> bool:
        """False if `epoch` is older than the current lease epoch (reject the message)."""
        ...

    async def reconcile(self, remote: Authority) -> bool:
        """Compare with a peer's view after reconnect. True if this device must stop the workload."""
        ...


@runtime_checkable
class MigrationManager(Service, Protocol):
    """P1. Checkpointed migration + workload registry. Publishes migration.status, authority.change."""

    def workloads(self) -> builtins.list[WorkloadManifest]: ...
    async def launch_workload(self, manifest_path: str) -> WorkloadManifest: ...
    async def start(self, workload_id: str, target_id: str, trigger: Trigger) -> MigrationStatus: ...
    async def abort(self, migration_id: str) -> MigrationStatus: ...
    def status(self, migration_id: str) -> MigrationStatus | None: ...
    def metrics(self, migration_id: str) -> MigrationMetrics | None: ...
    async def precopy(self, workload_id: str, target_id: str) -> MigrationMetrics:
        """Send changed checkpoints to `target_id` ahead of time; no authority change."""
        ...

    def list(self) -> builtins.list[MigrationStatus]: ...


@runtime_checkable
class RemoteService(Service, Protocol):
    """P4. Host side (capture, input injection, consent) and viewer WS. Publishes remote.session."""

    async def start_session(self, workload_id: str, viewer_id: str) -> RemoteSession: ...
    async def handle_viewer(self, websocket: WebSocket, session_id: str) -> None:
        """Owns /ws/remote/{sessionId}: binary JPEG frames out, JSON input events in."""
        ...

    def sessions(self) -> builtins.list[RemoteSession]: ...
