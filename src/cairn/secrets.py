"""Optional OS-keychain secret storage.

Config values may be the literal secret, an env var (resolved in config.py), or a
reference of the form ``keyring:NAME`` that is looked up in the OS keychain
(macOS Keychain, Windows Credential Manager, libsecret on Linux). This keeps
tokens out of plaintext config for desktop users while leaving the env-var path
intact for headless servers.

keyring is an optional dependency: ``pip install 'cairn-sync[secrets]'``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SERVICE = "cairn"
PREFIX = "keyring:"


class SecretError(Exception):
    pass


def keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
        from keyring.errors import NoKeyringError
        try:
            keyring.get_keyring()
        except NoKeyringError:
            return False
        return True
    except Exception:
        return False


def _kr():
    try:
        import keyring
        return keyring
    except ImportError as e:
        raise SecretError(
            "Keychain storage needs the 'keyring' package: "
            "pip install 'cairn-sync[secrets]'"
        ) from e


def set_secret(name: str, value: str) -> None:
    _kr().set_password(SERVICE, name, value)


def get_secret(name: str) -> str:
    value = _kr().get_password(SERVICE, name)
    if value is None:
        raise SecretError(f"No keychain secret named {name!r} (service '{SERVICE}').")
    return value


def delete_secret(name: str) -> None:
    try:
        _kr().delete_password(SERVICE, name)
    except Exception as e:  # noqa: BLE001 - delete is best-effort
        logger.debug("delete_secret(%s) failed: %s", name, e)


def resolve_secrets(tree):
    """Recursively replace any 'keyring:NAME' strings with the stored secret."""
    if isinstance(tree, dict):
        return {k: resolve_secrets(v) for k, v in tree.items()}
    if isinstance(tree, list):
        return [resolve_secrets(v) for v in tree]
    if isinstance(tree, str) and tree.startswith(PREFIX):
        return get_secret(tree[len(PREFIX):])
    return tree
