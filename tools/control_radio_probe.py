"""Explicit bench probe: encrypted RF ping through the camera's WFB tunnel.

No camera settings are changed and no private key bytes are read by Python.
The normal receiver must be stopped; the shared radio lock enforces that.
"""
import fcntl
import json
import os
import secrets
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from receiver import local_radio as base
from receiver.dual_radio import inventory, KNOWN_MACS


def checksum(data):
    data += b'\0' if len(data) % 2 else b''
    total = sum(struct.unpack('!%dH' % (len(data) // 2), data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def ping_packet(seq, nonce):
    icmp = struct.pack('!BBHHH', 8, 0, 0, 0x464c, seq) + nonce
    icmp = icmp[:2] + struct.pack('!H', checksum(icmp)) + icmp[4:]
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(icmp), seq, 0, 32, 1, 0,
                     socket.inet_aton('10.5.0.1'), socket.inet_aton('10.5.0.10'))
    ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
    packet = ip + icmp
    return struct.pack('!H', len(packet)) + packet


def echo_reply(data, nonce):
    while len(data) >= 2:
        length, = struct.unpack_from('!H', data)
        packet, data = data[2:2+length], data[2+length:]
        if len(packet) < 28 or packet[0] >> 4 != 4:
            continue
        offset = (packet[0] & 15) * 4
        if (packet[9] == 1 and packet[12:16] == socket.inet_aton('10.5.0.10')
                and packet[16:20] == socket.inet_aton('10.5.0.1')
                and len(packet) >= offset + 8 and packet[offset] == 0
                and packet[offset+4:offset+6] == b'FL' and packet[offset+8:] == nonce):
            return struct.unpack_from('!H', packet, offset+6)[0]
    return None


def main():
    root = base.ROOT / 'data'
    logs = Path(tempfile.mkdtemp(prefix='control-radio-', dir=root / 'logs'))
    children, handles, sockets = [], [], []
    result = {'operation': 'rf_control_echo', 'tx_requested': True, 'sent': 0, 'received': 0,
              'channel': 161, 'width': 20, 'uplink_port': 160, 'downlink_port': 32,
              'tx_power_index': 10, 'rtt_ms': [], 'camera_settings_changed': False}
    lock = (root / 'logs/.fit-lab-radio-prepare.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def spawn(args, name):
        handle = (logs / name).open('wb'); handles.append(handle)
        child = subprocess.Popen(list(map(str,args)),stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT)
        children.append(child)
        return child
    def port():
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1',0)); return sock.getsockname()[1]
    try:
        device=inventory()[0]
        report=logs/'efuse.json'; logical=logs/'logical.bin'
        prepare=spawn([base.DIAG,'--json','--report',report,'macos-efuse-dump','--vid','0x0bda','--pid','0x8812',
                       '--address',device['address'],'--logical-map-out',logical,'--i-understand-this-writes-control-registers'],'efuse.log')
        if prepare.wait(timeout=60) or json.loads(report.read_text()).get('result')!='pass':
            raise ValueError('EFUSE profile unavailable')
        mac,profile=base.derive_profile(logical.read_bytes(),expected_mac=None)
        if mac not in KNOWN_MACS: raise ValueError('Unverified adapter')
        result['adapter_mac']=mac
        receive=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sockets.append(receive)
        receive.bind(('127.0.0.1',0));receive.settimeout(.15)
        injector,aggregator,application=port(),port(),port()
        ready=logs/'ready.json'
        args=[base.DIAG,'--json','--report',logs/'radio.json','bridge-run','--macos-usbhost','--vid','0x0bda','--pid','0x8812',
              '--address',device['address'],'--init-before-tx','--firmware',base.FW,'--channel','161','--bandwidth','20',
              '--bind',f'127.0.0.1:{injector}','--duration-ms','20000','--max-datagrams','0','--rx-timeout-ms','5',
              '--tx-burst-limit','2','--tx-min-interval-us','1000','--ready-file',ready,'--no-heartbeat-led',
              '--mac-source',base.TABLE_ROOT/base.TABLE_BLOBS['mac'][0],'--bb-source',base.TABLE_ROOT/base.TABLE_BLOBS['bb'][0],
              '--rf-source',base.TABLE_ROOT/base.TABLE_BLOBS['rf'][0],'--cut-version','0','--package-type','0','--support-interface','2',
              '--support-platform','0','--wfb-link-id',base.LINK_ID,'--wfb-radio-port','32',
              '--rx-aggregator',f'127.0.0.1:{aggregator}','--rx-mcs-index','1','--tx-power-mode','manual-index','--tx-power-index','10',
              '--i-understand-this-writes-registers']
        for flag,value in profile.items(): args.extend(['--'+flag,value])
        radio=spawn(args,'radio.log')
        deadline=time.monotonic()+70
        while not ready.exists():
            if radio.poll() is not None or time.monotonic()>deadline: raise ValueError('Radio initialization failed')
            time.sleep(.2)
        key=base.get_key()
        rx=spawn([base.CODEC,'-a',aggregator,'-K',key,'-i',base.LINK_ID,'-p','32','-c','127.0.0.1','-u',receive.getsockname()[1]],'wfb-rx.log')
        tx=spawn([base.ROOT/'experiments/wfb-ng-codec-c1a160c4/wfb_tx','-d','-K',key,'-k','1','-n','2','-u',application,
                  '-i',base.LINK_ID,'-p','160','-B','20','-M','0','-T','20',f'127.0.0.1:{injector}'],'wfb-tx.log')
        sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sockets.append(sender)
        time.sleep(1)
        nonce=secrets.token_bytes(16);sent={};seen=set();start=time.monotonic();next_send=start
        while time.monotonic()-start < 14:
            now=time.monotonic()
            if radio.poll() is not None or rx.poll() is not None or tx.poll() is not None: raise ValueError('Radio helper exited')
            if result['sent'] < 10 and now>=next_send:
                seq=result['sent']+1;sent[seq]=now
                sender.sendto(ping_packet(seq,nonce),('127.0.0.1',application))
                result['sent']+=1;next_send=now+1
            try: data,_=receive.recvfrom(65535)
            except socket.timeout: continue
            seq=echo_reply(data,nonce)
            if seq in sent and seq not in seen:
                seen.add(seq);result['received']+=1
                result['rtt_ms'].append(round((time.monotonic()-sent[seq])*1000,2))
        result['result']='roundtrip_confirmed' if result['received'] else 'no_radio_reply'
        radio.wait(timeout=10)
    except Exception as exc:
        result.update(result='error',error=str(exc))
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired: child.kill();child.wait()
        for handle in handles: handle.close()
        for sock in sockets: sock.close()
        lock.close()
        (logs/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'log_directory':str(logs),**result},ensure_ascii=False))


if __name__=='__main__': main()
