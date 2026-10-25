from __future__ import annotations

from typing import Any


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "error",
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.retry_after = retry_after


class Provider:
    id = ""
    name = ""
    icon = ""

    def detected(self) -> bool:
        raise NotImplementedError

    def fetch(self) -> dict[str, Any]:
        raise NotImplementedError
