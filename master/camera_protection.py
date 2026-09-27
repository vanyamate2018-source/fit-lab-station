"""Public protection status; enrollment is not proof of complete protection."""
import json
from master.camera_credentials import security_receipt_path


def protection_status(root, fingerprint, bindings):
    try:
        receipt = json.loads(security_receipt_path(root, fingerprint).read_text())
    except (OSError, ValueError):
        receipt = {}
    password = (receipt.get('stage') == 'protected' and receipt.get('old_password_rejected') is True
                and receipt.get('api_verified') is True)
    binding = next((p for p in bindings if p.get('ssh_fingerprint') == fingerprint), {})
    public = binding.get('drone_public')
    unique = bool(binding and public and not binding.get('legacy_import') and binding.get('stage') == 'committed'
                  and not any(p.get('identity') != binding.get('identity') and
                              (p.get('drone_public') == public or p.get('gs_public') == binding.get('gs_public'))
                              for p in bindings))
    text = ('Пароль и радиоключи индивидуальные' if password and unique else
            'Пароль защищён · проверьте радиоключи' if password else
            'Индивидуальные радиоключи · защитите вход' if unique else 'Нужна настройка защиты по LAN')
    if receipt.get('stage') == 'pending':
        text = 'Нужно завершить проверку защиты по LAN'
    return dict(password_verified=password, radio_keys_individual=unique, text=text,
                renew_keys=bool(binding.get('legacy_import')))
