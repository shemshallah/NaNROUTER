"""Authenticated Python facade over the BS0DB/MC0DB wave store.

The facade is deliberately thin: it authenticates a caller role, then delegates
to :class:`runner_riddle.wave_store.WaveStore`.  It performs no wave
mathematics, owns no persistence, starts no HTTP server, and never writes a
service credential to the database.  Tokens are kept only as SHA-256 digests in
process memory and are compared with :func:`hmac.compare_digest`.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Iterable

from .wave_store import WaveStore

MIN_TOKEN_LENGTH = 16


class WaveServiceError(ValueError):
    """Base class for wave-service configuration and authorization failures."""


class WaveServiceConfigError(WaveServiceError):
    """Raised when the service is constructed with missing, weak, or reused tokens."""


class WaveServiceAuthError(WaveServiceError, PermissionError):
    """Raised when a caller token is missing or does not hold the required role."""


def _token_digest(token: str) -> bytes:
    """Return a fixed-size representation suitable for constant-time comparison."""
    return hashlib.sha256(token.encode("utf-8")).digest()


class WaveService:
    """Role-authenticated control-plane facade for a :class:`WaveStore`.

    Roles are intentionally separate:

    ``submit``
        Enqueue jobs and append trace/seal/signature evidence.
    ``worker``
        Lease, complete, and fail jobs.
    ``admin``
        Register capabilities and append evidence as an administrative override.

    The constructor requires three distinct tokens of at least
    :data:`MIN_TOKEN_LENGTH` characters.  A token is never passed to the store,
    never returned by ``health()``, and never included in an exception message.
    """

    def __init__(self, store: WaveStore, submit_token: str, worker_token: str,
                 admin_token: str) -> None:
        tokens = {
            "submit": submit_token,
            "worker": worker_token,
            "admin": admin_token,
        }
        for role, token in tokens.items():
            if not isinstance(token, str) or not token.strip():
                raise WaveServiceConfigError(f"{role}_token is required")
            if len(token) < MIN_TOKEN_LENGTH:
                raise WaveServiceConfigError(
                    f"{role}_token must be at least {MIN_TOKEN_LENGTH} characters"
                )
        roles = tuple(tokens)
        for index, left in enumerate(roles):
            for right in roles[index + 1:]:
                if hmac.compare_digest(
                    tokens[left].encode("utf-8"), tokens[right].encode("utf-8")
                ):
                    raise WaveServiceConfigError(
                        "submit, worker, and admin tokens must be distinct"
                    )

        self.store = store
        self._roles = roles
        # Retain only digests: the plaintext credentials stay in the caller's
        # configuration/secret manager, not in this object's observable state.
        self._token_digests = {
            role: _token_digest(token) for role, token in tokens.items()
        }

    def __repr__(self) -> str:
        return "WaveService(roles=submit,worker,admin)"

    # -- Authorization --------------------------------------------------------

    def _authorize(self, token: Any, allowed_roles: Iterable[str]) -> None:
        """Require *token* to hold one of *allowed_roles*.

        Every configured role is compared on every call so the work performed
        does not depend on which role (if any) matched.
        """
        if not isinstance(token, str) or not token:
            raise WaveServiceAuthError("an authentication token is required")

        supplied = _token_digest(token)
        permitted = False
        for role in self._roles:
            matched = hmac.compare_digest(supplied, self._token_digests[role])
            if role in allowed_roles:
                permitted = permitted or matched
        if not permitted:
            raise WaveServiceAuthError(
                "the supplied token does not authorize this operation"
            )

    def _authorize_submit_or_admin(self, token: Any) -> None:
        self._authorize(token, ("submit", "admin"))

    # -- Jobs and leases (MC0DB) ---------------------------------------------

    def submit_job(self, token: str, job_id: str, universe_id: str,
                   operator_digest: str, generation: int, payload: Any = None,
                   now_tick: int = 0, *, kind: str = "wave",
                   operator_id: str | None = None,
                   precision: str | None = None,
                   workspace: int = 0) -> dict[str, Any]:
        """Enqueue an idempotent job.  Requires the ``submit`` token."""
        self._authorize(token, ("submit",))
        return self.store.enqueue_job(
            job_id,
            universe_id=universe_id,
            generation=generation,
            operator_digest=operator_digest,
            payload=payload,
            kind=kind,
            operator_id=operator_id,
            precision=precision,
            workspace=workspace,
            nanclock_tick=now_tick,
        )

    def lease_job(self, token: str, owner: str, now_tick: int,
                  lease_ticks: int = 64, *,
                  expected_generation: int | None = None,
                  max_attempts: int = 8,
                  job_id: str | None = None) -> dict[str, Any] | None:
        """Lease one queued job.  Requires the ``worker`` token."""
        self._authorize(token, ("worker",))
        return self.store.lease_job(
            owner=owner,
            now_tick=now_tick,
            lease_ticks=lease_ticks,
            expected_generation=expected_generation,
            max_attempts=max_attempts,
            job_id=job_id,
        )

    def complete_job(self, token: str, job_id: str, lease_token: str,
                     lease_epoch: int, result_digest: str, now_tick: int, *,
                     result_generation: int | None = None,
                     lease_owner: str | None = None) -> dict[str, Any]:
        """Complete a leased job.  Requires the ``worker`` token."""
        self._authorize(token, ("worker",))
        return self.store.complete_job(
            job_id,
            lease_token=lease_token,
            lease_epoch=lease_epoch,
            result_digest=result_digest,
            now_tick=now_tick,
            result_generation=result_generation,
            lease_owner=lease_owner,
        )

    def fail_job(self, token: str, job_id: str, lease_token: str,
                 lease_epoch: int, now_tick: int, error: str, *,
                 lease_owner: str | None = None) -> dict[str, Any]:
        """Fail a leased job.  Requires the ``worker`` token."""
        self._authorize(token, ("worker",))
        return self.store.fail_job(
            job_id,
            lease_token=lease_token,
            lease_epoch=lease_epoch,
            now_tick=now_tick,
            error=error,
            lease_owner=lease_owner,
        )

    # -- Capability registry (MC0DB) -----------------------------------------

    def register_capability(self, token: str, kernel_id: str, runner_id: str,
                            verified_digest: str, workspace: int,
                            precision: str, *, status: str = "declared",
                            epoch: int = 1,
                            nanclock_tick: int = 0) -> dict[str, Any]:
        """Register a runner capability.  Requires the ``admin`` token."""
        self._authorize(token, ("admin",))
        return self.store.register_capability(
            kernel_id=kernel_id,
            runner_id=runner_id,
            verified_digest=verified_digest,
            workspace=workspace,
            precision=precision,
            status=status,
            epoch=epoch,
            nanclock_tick=nanclock_tick,
        )

    # -- Evidence (BS0DB) -----------------------------------------------------

    def store_trace(self, token: str, universe_id: str, generation: int,
                    digest: str, producer: str, nanclock_tick: int,
                    signature: str, *, payload: Any = None,
                    payload_blob: bytes | None = None,
                    trace_id: str | None = None,
                    job_id: str | None = None) -> dict[str, Any]:
        """Append immutable trace evidence.  Requires ``submit`` or ``admin``."""
        self._authorize_submit_or_admin(token)
        return self.store.append_trace(
            universe_id=universe_id,
            generation=generation,
            digest=digest,
            producer=producer,
            nanclock_tick=nanclock_tick,
            signature=signature,
            payload=payload,
            payload_blob=payload_blob,
            trace_id=trace_id,
            job_id=job_id,
        )

    def store_seal(self, token: str, universe_id: str, generation: int,
                   digest: str, producer: str, nanclock_tick: int,
                   signature: str, *, payload: Any = None,
                   payload_blob: bytes | None = None,
                   seal_id: str | None = None,
                   job_id: str | None = None) -> dict[str, Any]:
        """Append immutable seal evidence.  Requires ``submit`` or ``admin``."""
        self._authorize_submit_or_admin(token)
        return self.store.append_seal(
            universe_id=universe_id,
            generation=generation,
            digest=digest,
            producer=producer,
            nanclock_tick=nanclock_tick,
            signature=signature,
            payload=payload,
            payload_blob=payload_blob,
            seal_id=seal_id,
            job_id=job_id,
        )

    def store_signature(self, token: str, universe_id: str, generation: int,
                        kind: str, digest: str, producer: str,
                        nanclock_tick: int, signature: str, *,
                        payload: Any = None, payload_blob: bytes | None = None,
                        signature_id: str | None = None) -> dict[str, Any]:
        """Append immutable signature evidence.  Requires ``submit`` or ``admin``."""
        self._authorize_submit_or_admin(token)
        return self.store.append_signature(
            universe_id=universe_id,
            generation=generation,
            kind=kind,
            digest=digest,
            producer=producer,
            nanclock_tick=nanclock_tick,
            signature=signature,
            payload=payload,
            payload_blob=payload_blob,
            signature_id=signature_id,
        )

    # Familiar aliases matching WaveStore's append_* names.
    append_trace = store_trace
    append_seal = store_seal
    append_signature = store_signature

    # -- Observability --------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return the store's unauthenticated, token-free health report."""
        return self.store.health()


__all__ = [
    "MIN_TOKEN_LENGTH",
    "WaveService",
    "WaveServiceAuthError",
    "WaveServiceConfigError",
    "WaveServiceError",
]
