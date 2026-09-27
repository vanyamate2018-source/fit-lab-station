from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
start=s.index('void injector_loop('); end=s.index('void ',start+6)
part=s[start:end]
old='open_udp_socket_for_rx(bind_port, rcv_buf)'
new='open_udp_socket_for_rx(bind_port, rcv_buf, 0x7f000001)'
if old in part:
    p.write_text(s[:start]+part.replace(old,new)+s[end:])
elif new not in part: raise SystemExit('Unexpected injector source')
