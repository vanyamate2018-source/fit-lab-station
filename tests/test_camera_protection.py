import json
from master.camera_protection import protection_status
from master.camera_credentials import security_receipt_path


def test_enrollment_and_legacy_keys_do_not_mean_protected(tmp_path):
    p=dict(identity='one',ssh_fingerprint='pin',stage='committed',drone_public='d',gs_public='g',legacy_import=True)
    assert protection_status(tmp_path,'pin',[p])['renew_keys']
    assert not protection_status(tmp_path,'pin',[p])['radio_keys_individual']
    path=security_receipt_path(tmp_path,'pin');path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(stage='protected',old_password_rejected=True,api_verified=True)))
    assert protection_status(tmp_path,'pin',[p])['password_verified']
    p.pop('legacy_import')
    assert protection_status(tmp_path,'pin',[p])['radio_keys_individual']
    assert not protection_status(tmp_path,'pin',[p,dict(p,identity='two')])['radio_keys_individual']


def test_incomplete_password_proof_never_claims_protection(tmp_path):
    path=security_receipt_path(tmp_path,'pin');path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(stage='protected',api_verified=True)))
    assert not protection_status(tmp_path,'pin',[])['password_verified']
