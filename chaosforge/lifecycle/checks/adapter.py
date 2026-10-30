from abc import ABC, abstractmethod
from typing import Any


class ResourceAdapter(ABC):
    """
    Provider-specific adapter used by common lifecycle checks.

    Adapters translate provider APIs into a normalized resource
    snapshot. The lifecycle framework remains provider-agnostic.
    """

    name: str = "resource-adapter"

    @abstractmethod
    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        """
        Capture a normalized snapshot of the target resource.

        The snapshot may contain the following normalized sections:

        - exists
        - identity
        - state
        - configuration
        - health
        - metadata

        Adapters only need to populate sections that are meaningful
        for the resource type.
        """
        raise NotImplementedError
