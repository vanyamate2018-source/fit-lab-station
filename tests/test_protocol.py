from shared.protocol import PROTOCOL_NAME, PROTOCOL_VERSION

def test_protocol_identity():
    assert PROTOCOL_NAME == "fit-lab"
    assert PROTOCOL_VERSION >= 1
