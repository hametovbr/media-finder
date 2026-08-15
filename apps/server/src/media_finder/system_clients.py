"""Stable identities for environment-owned download clients."""

from sqlalchemy.orm import Session

from .models import DownloadClientInstance

SYSTEM_QBITTORRENT_ID = "00000000-0000-5000-8000-000000000001"


def ensure_system_qbittorrent(session: Session) -> DownloadClientInstance:
    """Return the sole system-owned qBittorrent persistence identity."""

    expected_name = "qBittorrent"
    expected_module = "qbittorrent"
    instance = session.get(DownloadClientInstance, SYSTEM_QBITTORRENT_ID)
    if instance is None:
        instance = DownloadClientInstance(
            id=SYSTEM_QBITTORRENT_ID,
            name=expected_name,
            module_key=expected_module,
            config_payload={},
            system_owned=True,
        )
        session.add(instance)
        session.commit()
    elif (
        instance.name != expected_name
        or instance.module_key != expected_module
        or instance.config_payload
        or not instance.system_owned
        or instance.archived_at is not None
    ):
        raise RuntimeError("system_qbittorrent_identity_invalid")
    return instance
