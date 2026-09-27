from shared.link_health import LinkHealth


def sample(lost, delivered, phase="video"):
    return {"phase": phase, "frame_age": .1, "fps": 60, "mbps": 4,
            "radio": {"totals": {"lost_packets": lost, "outgoing_packets": delivered}}}


def test_window_uses_counter_deltas_without_counting_old_losses():
    health = LinkHealth()
    health.add(sample(100, 1000))
    result = health.add(sample(102, 1198))
    assert result["lost_packets"] == 2
    assert result["loss_percent"] == 1
    assert result["status"] == "losses"
    assert result["end_to_end_latency_ms"] is None
    assert health.add(sample(0, 0))["lost_packets"] == 2


def test_stale_frames_cannot_look_like_healthy_fps():
    health = LinkHealth()
    result = health.add(sample(0, 0, "waiting"))
    assert result["fps_median"] == 0
    assert result["status"] == "no_video"
