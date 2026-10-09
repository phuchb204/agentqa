from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.models import ProviderRoute
from agentqa.platform.artifacts.service import ArtifactService
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.events.service import EventService
from agentqa.platform.identity.authorization import AuthorizationService
from agentqa.platform.identity.bootstrap import LocalBootstrapService
from agentqa.platform.identity.sessions import DEFAULT_SESSION_TTL, SessionService, TokenService
from agentqa.platform.identity.users import UserService
from agentqa.platform.revisions.service import RevisionService
from agentqa.platform.runs.service import RunService
from agentqa.platform.security.credentials import CredentialService, EnvelopeService, MasterKeyring
from agentqa.platform.security.grants import GrantService
from agentqa.platform.security.origin import OriginPolicy
from agentqa.platform.security.redaction import RedactionService
from agentqa.platform.security.taint import TAINT_REGISTRY, TaintRegistry
from agentqa.platform.storage.database import create_engine
from agentqa.platform.storage.roles import ROLE_API
from agentqa.platform.usage.service import UsageLedgerService

DEFAULT_PROVIDER_ENDPOINTS: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_ZEN: "https://opencode.ai/zen/v1",
    ProviderRoute.OPENCODE_GO: "https://opencode.ai/zen/go/v1",
}


@dataclass(frozen=True)
class RuntimeProfile:
    kind: Literal["local", "shared"]
    allowed_origins: frozenset[str] = frozenset()

    @classmethod
    def local(cls) -> RuntimeProfile:
        return cls(kind="local")

    @classmethod
    def shared(cls, allowed_origins: frozenset[str]) -> RuntimeProfile:
        profile = cls(kind="shared", allowed_origins=allowed_origins)
        profile.origin_policy()
        return profile

    def origin_policy(self) -> OriginPolicy:
        if self.kind == "shared":
            return OriginPolicy.shared(self.allowed_origins)
        return OriginPolicy.local()


@dataclass
class PlatformRuntime:
    profile: RuntimeProfile
    engines: Mapping[str, AsyncEngine]
    users: UserService
    sessions: SessionService
    tokens: TokenService
    authorization: AuthorizationService
    bootstrap: LocalBootstrapService
    taint: TaintRegistry
    redaction: RedactionService
    envelope: EnvelopeService
    credentials: CredentialService
    grants: GrantService
    revisions: RevisionService
    runs: RunService
    events: EventService
    usage: UsageLedgerService
    artifacts: ArtifactService

    @classmethod
    def build(
        cls,
        *,
        profile: RuntimeProfile,
        dsn_by_role: Mapping[str, str],
        master_keyring: MasterKeyring | None = None,
        taint: TaintRegistry | None = None,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
        provider_endpoints: Mapping[ProviderRoute, str] | None = None,
        artifact_store: FileSystemBlobStore | None = None,
    ) -> PlatformRuntime:
        engines = {role: create_engine(dsn) for role, dsn in dsn_by_role.items()}
        api_engine = engines[ROLE_API]
        registry = taint or TAINT_REGISTRY
        redaction = RedactionService(registry)
        keyring = master_keyring or MasterKeyring.synthetic()
        envelope = EnvelopeService(keyring)
        credentials = CredentialService(envelope)
        sessions = SessionService(api_engine, ttl=session_ttl)
        bootstrap = LocalBootstrapService(policy=profile.origin_policy(), sessions=sessions)
        grants = GrantService(
            resolver=_grant_resolver(api_engine, credentials),
            provider_origins=provider_endpoints or DEFAULT_PROVIDER_ENDPOINTS,
        )
        events = EventService(api_engine)
        store = artifact_store or FileSystemBlobStore(Path("artifacts") / "store")
        return cls(
            profile=profile,
            engines=engines,
            users=UserService(api_engine),
            sessions=sessions,
            tokens=TokenService(api_engine),
            authorization=AuthorizationService(api_engine),
            bootstrap=bootstrap,
            taint=registry,
            redaction=redaction,
            envelope=envelope,
            credentials=credentials,
            grants=grants,
            revisions=RevisionService(api_engine),
            runs=RunService(api_engine, events=events),
            events=events,
            usage=UsageLedgerService(),
            artifacts=ArtifactService(api_engine, store, taint=registry),
        )

    async def aclose(self) -> None:
        for engine in self.engines.values():
            await engine.dispose()


def _grant_resolver(engine: AsyncEngine, credentials: CredentialService):
    from agentqa.contracts.values import SensitiveValue
    from agentqa.platform.security.grants import SecretGrant
    from agentqa.platform.storage.database import create_session_factory
    from agentqa.platform.storage.scope import set_scope

    factory = create_session_factory(engine)

    async def resolve(grant: SecretGrant) -> SensitiveValue:
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=grant.principal, workspace_id=grant.workspace_id)
            return await credentials.resolve(
                session,
                workspace_id=grant.workspace_id,
                credential_id=grant.credential_id,
                version=grant.credential_version,
            )

    return resolve
