"""Capture test recording wire bytes during a fake migration.

Asserts that no plaintext state, checkpoint payload, or manifest text appears on the wire.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from contract.contract import (
    MigChunk,
    MigPrepare,
    RuntimeReq,
    WorkloadManifest,
)
from teleport.core import Settings, create_app
from teleport.security import DeviceIdentity, SecureSession


def test_wire_capture_during_fake_migration(tmp_path: Path) -> None:
    server_home = tmp_path / "server"
    client_home = tmp_path / "client"

    server_settings = Settings(home=server_home, port=8765, deviceName="Target Node")
    app = create_app(server_settings)

    secret_workload_id = "SECRET_WORKLOAD_PAYLOAD_ABC_xyz"
    secret_state_content = b"SUPER_SECRET_CHECKPOINT_STATE_BYTES_9876543210"
    secret_manifest_token = "TOP_SECRET_MANIFEST_COMMAND_ARG_VAL"

    captured_wire_frames: list[str] = []

    with TestClient(app) as test_client:
        with test_client.websocket_connect("/peer") as ws:
            # Step 1: Intercept server KEX
            server_kex_raw = ws.receive_text()
            captured_wire_frames.append(server_kex_raw)
            srv_kex = json.loads(server_kex_raw)
            assert srv_kex["t"] == "kex"

            server_id_bytes = base64.b64decode(srv_kex["identityKey"])
            server_eph_bytes = base64.b64decode(srv_kex["ephemeralKey"])
            assert DeviceIdentity.verify(server_eph_bytes, srv_kex["signature"], server_id_bytes)

            # Step 2: Client sends KEX
            client_session = SecureSession(client_home)
            client_kex = {
                "t": "kex",
                "deviceId": "dev-client-node",
                "identityKey": client_session.identity.public_key_b64(),
                "ephemeralKey": base64.b64encode(client_session.ephemeral_public_key()).decode("ascii"),
                "signature": client_session.sign(client_session.ephemeral_public_key()),
            }
            client_kex_str = json.dumps(client_kex)
            captured_wire_frames.append(client_kex_str)
            ws.send_text(client_kex_str)

            client_session.establish(server_eph_bytes, server_id_bytes, is_initiator=True)

            # Step 3: Receive server encrypted PeerHello
            srv_hello_enc = ws.receive_text()
            captured_wire_frames.append(srv_hello_enc)

            # Step 4: Send MigPrepare with sensitive manifest text
            manifest = WorkloadManifest(
                id=secret_workload_id,
                name="Confidential Workload",
                command=f"python run.py --key={secret_manifest_token}",
                runtime=RuntimeReq(name="python", minVersion="3.11"),
                arch=["x86_64"],
                os=["linux"],
                minRamMb=1024,
                minCpuCores=2,
                minDiskMb=500,
                needsGpu=False,
                libs=[],
                checkpoints=[],
                remoteCapable=False,
            )
            mig_prep = MigPrepare(
                migrationId="mig-12345",
                manifest=manifest,
                checkpoints=[],
                epoch=1,
                signature=client_session.sign(manifest.model_dump_json().encode("utf-8")),
            )
            prep_bytes = mig_prep.model_dump_json().encode("utf-8")
            enc_prep = base64.b64encode(client_session.encrypt(prep_bytes)).decode("ascii")
            captured_wire_frames.append(enc_prep)
            ws.send_text(enc_prep)

            # Step 5: Send MigChunk containing secret checkpoint state
            mig_chunk = MigChunk(
                migrationId="mig-12345",
                checkpointId="chk-001",
                index=0,
                total=1,
                dataB64=base64.b64encode(secret_state_content).decode("ascii"),
                sha256="fake_sha256",
                epoch=1,
            )
            chunk_bytes = mig_chunk.model_dump_json().encode("utf-8")
            enc_chunk = base64.b64encode(client_session.encrypt(chunk_bytes)).decode("ascii")
            captured_wire_frames.append(enc_chunk)
            ws.send_text(enc_chunk)

    # Assert wire capture properties
    assert len(captured_wire_frames) >= 4

    raw_wire_dump = "\n".join(captured_wire_frames)
    raw_wire_bytes = raw_wire_dump.encode("utf-8")

    # Assert that NO plaintext secret appears anywhere in the captured wire bytes
    assert secret_workload_id not in raw_wire_dump
    assert secret_manifest_token not in raw_wire_dump
    assert secret_state_content not in raw_wire_bytes
    assert b"SUPER_SECRET" not in raw_wire_bytes

    # Assert that the post-handshake frames are strictly valid AES-GCM ciphertexts
    for enc_frame in captured_wire_frames[2:]:
        # Frame is base64 encoded
        cipher_bytes = base64.b64decode(enc_frame)
        # Nonce is 12 bytes + ciphertext is >= 16 bytes auth tag
        assert len(cipher_bytes) >= 28
        # The encrypted payload itself does not contain the plaintext strings
        assert secret_state_content not in cipher_bytes
        assert secret_workload_id.encode("utf-8") not in cipher_bytes
