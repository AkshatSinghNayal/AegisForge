"""Provider boundary: local authenticated encryption; cloud adapters are future work."""

from typing import Protocol
from uuid import UUID

from cryptography.fernet import Fernet

from aegis_api.conventions import APIError
from aegis_api.settings import Settings


class SecretStore(Protocol):
    def seal(self, organization_id: UUID, reference_id: UUID, value: str) -> str: ...
    def open(
        self, organization_id: UUID, reference_id: UUID, ciphertext: str
    ) -> str: ...


class LocalSecretStore:
    def __init__(self, settings: Settings):
        if settings.profile == "prod":
            raise APIError(
                503,
                "secret_provider_unavailable",
                "A production secret provider must be configured.",
            )
        try:
            self.fernet = Fernet(settings.local_secret_key.get_secret_value())
        except (ValueError, TypeError):
            raise APIError(
                503,
                "secret_provider_unavailable",
                "Configure the local secret encryption key.",
            ) from None

    def seal(self, organization_id: UUID, reference_id: UUID, value: str) -> str:
        return self.fernet.encrypt(
            f"{organization_id}:{reference_id}:{value}".encode()
        ).decode()

    def open(self, organization_id: UUID, reference_id: UUID, ciphertext: str) -> str:
        value = self.fernet.decrypt(ciphertext).decode()
        prefix = f"{organization_id}:{reference_id}:"
        if not value.startswith(prefix):
            raise ValueError("Secret scope mismatch")
        return value[len(prefix) :]


class OAuthProvider(Protocol):
    """Future adapter only; no OAuth tokens or fake authorization are accepted."""

    async def access_secret_reference(
        self, organization_id: UUID, target_id: UUID
    ) -> UUID: ...
