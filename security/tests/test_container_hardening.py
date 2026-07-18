"""ADR-0014 — Container hardening.

Control: the runtime image and its k8s securityContext enforce non-root, a
read-only root filesystem, dropped capabilities, a seccomp profile, and no shell
in the runtime image. These are asserted by reading the shipped artifacts so a
regression (e.g. someone flipping readOnlyRootFilesystem to false) fails the
build.
"""

from __future__ import annotations

import json
import os

INGEST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "services",
    "watertwin-ingest",
)
DOCKERFILE = os.path.join(INGEST, "Dockerfile")
DEPLOYMENT = os.path.join(INGEST, "deploy", "deployment.yaml")
SECCOMP = os.path.join(INGEST, "deploy", "seccomp.json")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_runtime_image_is_distroless_nonroot_no_shell():
    text = _read(DOCKERFILE)
    # Distroless runtime => no shell, no package manager in the runtime image.
    assert "distroless" in text
    assert "nonroot" in text
    assert "USER 65532:65532" in text
    # The runtime stage must not install a shell or run apt in the final image.
    runtime_stage = text.split("FROM gcr.io/distroless", 1)[1]
    assert "apt-get" not in runtime_stage
    assert "/bin/sh" not in runtime_stage
    assert "/bin/bash" not in runtime_stage


def test_deployment_enforces_nonroot():
    text = _read(DEPLOYMENT)
    assert "runAsNonRoot: true" in text
    assert "runAsUser: 65532" in text


def test_deployment_enforces_readonly_rootfs():
    assert "readOnlyRootFilesystem: true" in _read(DEPLOYMENT)


def test_deployment_disables_privilege_escalation():
    assert "allowPrivilegeEscalation: false" in _read(DEPLOYMENT)


def test_deployment_drops_all_capabilities():
    text = _read(DEPLOYMENT)
    assert "capabilities:" in text
    assert "drop:" in text
    # The dropped-capability list contains ALL.
    drop_block = text.split("drop:", 1)[1]
    assert "- ALL" in drop_block.split("resources:", 1)[0]


def test_deployment_sets_seccomp_profile():
    assert "seccompProfile:" in _read(DEPLOYMENT)


def test_seccomp_profile_defaults_to_deny():
    profile = json.loads(_read(SECCOMP))
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    # The allowlist must be non-empty (the app + sandbox need real syscalls).
    assert profile["syscalls"]
    assert any(s["action"] == "SCMP_ACT_ALLOW" for s in profile["syscalls"])
