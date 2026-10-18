"""Eval providers: register local/docker in the production map."""

from app.services.sandbox.service import Providers
from providers.docker_provider import DockerProvider
from providers.local_provider import LocalProvider


def registerEvalProviders() -> None:
    """Register the eval sandbox providers. Idempotent."""
    Providers["local"] = LocalProvider
    Providers["docker"] = DockerProvider


__all__ = ["registerEvalProviders"]
