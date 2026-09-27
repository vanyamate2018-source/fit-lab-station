from shared.camera_presets import resolution_choices, video_presets


def test_resolution_keeps_current_custom_size_and_honours_camera_enum():
    assert resolution_choices({'value': '1440x1080', 'enum': ['1280x720']}) == [
        ('1440 × 1080', '1440x1080'), ('1280 × 720', '1280x720')]


def test_modes_cannot_exceed_firmware_fps_or_resolution_choices():
    schema = {'properties': {'video0': {'properties': {
        'size': {'type': 'string', 'enum': ['1280x720']},
        'fps': {'type': 'integer', 'maximum': 30}}}}}
    config = {'video0': {'size': '1280x720', 'fps': 25, 'codec': 'h264'}}
    assert video_presets(schema, config) == [('720p · 30 FPS', {'video0.size': '1280x720', 'video0.fps': 30})]
    assert config['video0']['fps'] == 25


def test_missing_or_readonly_camera_controls_have_no_modes():
    assert video_presets({}, {}) == []
    schema = {'properties': {'video0': {'properties': {
        'size': {'type': 'string', 'readOnly': True}, 'fps': {'type': 'integer'}}}}}
    assert video_presets(schema, {'video0': {'size': '1280x720', 'fps': 60}}) == []
