from unittest.mock import Mock

import pytest

from master.camera_credentials import CameraCredentialStore
from master.credential_backends import SystemVault


def test_secure_provider_persists_independent_accounts_without_local_files(tmp_path):
    items = {}
    provider = Mock()
    provider.set_password.side_effect = lambda service, account, value: items.update({(service, account): value})
    provider.get_password.side_effect = lambda service, account: items.get((service, account))
    store = CameraCredentialStore(tmp_path, SystemVault(provider))
    store.durable_write('camera:one', ('root', 'one-secret'))
    store.durable_write('camera:two', ('root', 'two-secret'))
    restarted = CameraCredentialStore(tmp_path, SystemVault(provider))
    assert restarted.load('one') == ('root', 'one-secret')
    assert restarted.load('two') == ('root', 'two-secret')
    assert not list(tmp_path.iterdir())


def test_locked_vault_never_confirms_durable_password_change(tmp_path):
    provider = Mock()
    provider.set_password.side_effect = RuntimeError('secret must not escape')
    store = CameraCredentialStore(tmp_path, SystemVault(provider))
    with pytest.raises(OSError) as exc:
        store.durable_write('camera:one', ('root', 'private-password'))
    assert 'private-password' not in str(exc.value)
    assert 'secret must not escape' not in str(exc.value)


def test_unsupported_os_does_not_fall_back_to_plaintext():
    with pytest.raises(OSError):
        SystemVault.for_platform('unknown')
