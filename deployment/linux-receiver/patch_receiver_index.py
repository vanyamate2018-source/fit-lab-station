"""Preserve physical RX identity when each adapter has its own process."""
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = "rx[i].reset(new Receiver(argv[optind + i], i, channel_id, agg.get(), rcv_buf_size));"
new = """// FIT-LAB: independent workers retain their physical RX slot.
        int receiver_index = i;
        const char *slot = getenv("FITLAB_RX_SLOT");
        if (slot) {
            if (nfds != 1 || (strcmp(slot, "0") != 0 && strcmp(slot, "1") != 0 && strcmp(slot, "2") != 0))
                throw runtime_error("Invalid FITLAB_RX_SLOT");
            receiver_index = slot[0] - '0';
        }
        rx[i].reset(new Receiver(argv[optind + i], receiver_index, channel_id, agg.get(), rcv_buf_size));"""
previous = new.replace(' && strcmp(slot, "2") != 0', '')
if previous in s:
    p.write_text(s.replace(previous, new))
elif new not in s:
    if s.count(old) != 1: raise SystemExit("Unexpected receiver source; patch refused")
    p.write_text(s.replace(old, new))
