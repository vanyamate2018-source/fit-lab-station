"""Decoder recovery depends on media progress, never receiver count."""


def recovery_reason(now, previous_packet, current_packet, last_frame,
                    last_restart, source_changed=False):
    # The second RX may disappear while the first still produces good frames.
    # Source diagnostics alone must not interrupt a healthy picture.
    if last_frame and now - last_frame < .5:
        return None
    if now - last_restart < 3:
        return None
    if (previous_packet and current_packet > previous_packet
            and current_packet - previous_packet > 2):
        return 'transport_resumed'
    if source_changed:
        return 'source_restarted'
    return None


def decoder_stalled(now, last_packet, last_frame, last_restart):
    # A silent radio is not a decoder fault. Also allow an initial keyframe.
    return bool(last_packet and now - last_packet < 1
                and now - max(last_frame, last_restart) > 3
                and now - last_restart > 5)
