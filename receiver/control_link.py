"""Optional WFB command service. Its failure cannot stop video reception."""
import secrets
import os
import socket
import subprocess
import time
import sys
from collections import deque
from receiver import local_radio as base
from shared.control_packets import echo_replies, ping_packet, ssh_records
from receiver.tx_diversity import TxDiversity


class ControlLink:
    def __init__(self, logs, key, aggregator_port=None):
        self.logs = logs
        self.children, self.sockets = [], []
        self.commands = []
        self.retry_after = 0
        self.restarts = 0
        self.state = {'state': 'starting', 'sent': 0, 'replies': 0, 'rtt_ms': None}
        self.nonce, self.pending = secrets.token_bytes(16), {}
        self.last_ping = self.last_reply = 0
        self.sequence = 0
        self.echo_outcomes = deque(maxlen=120)
        self.echo_timeouts = 0
        self.failed = False
        self.diversity = TxDiversity()
        # Verified on the bench in both directions. Keep an explicit opt-out
        # for diagnosing a future adapter with a different hardware profile.
        self.diversity_enabled = os.environ.get('FIT_LAB_TX_DIVERSITY', '1') == '1'
        self.tx_job = self.tx_process = None
        self.socket_path = logs / 'command.sock'
        try:
            self.encoded = self.udp(0)
            self.injector = self.encoded.getsockname()[1]
            self.down = self.udp(0)
            self.gateway = self.udp(56550)
            self.sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self.sender.setblocking(False)
            self.sockets.append(self.sender)
            self.aggregator = aggregator_port or base.free_aggregator_port()
            embedded = os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1'
            codec = '/usr/local/libexec/fit-lab/wfb_rx' if embedded else base.CODEC
            encoder = '/usr/local/libexec/fit-lab/wfb_tx' if embedded else base.ROOT/'experiments/wfb-ng-codec-c1a160c4/wfb_tx'
            ssh_bridge = base.ROOT/'tools/wfb-radio-ssh' if embedded else base.REPO/'target/release/wfb-radio-ssh'
            self.spawn([codec, '-a', self.aggregator, '-K', key, '-i', base.LINK_ID,
                        '-p', '32', '-c', '127.0.0.1', '-u', self.down.getsockname()[1]], 'control-rx.log')
            from receiver.udp_ready import wait_for_udp_receiver
            wait_for_udp_receiver(self.children[-1], self.aggregator)
            # Explicit bench override; keep the robust default until measured.
            tx_mcs = '1' if os.environ.get('FIT_LAB_TX_MCS') == '1' else '0'
            self.state['tx_mcs'] = int(tx_mcs)
            self.spawn([encoder, '-d', '-K', key,
                        '-k', '1', '-n', '2', '-U', self.socket_path, '-i', base.LINK_ID,
                        '-p', '160', '-B', '20', '-M', tx_mcs, '-T', '20',
                        '-S', '1' if os.environ.get('FIT_LAB_TX_STBC') == '1' else '0',
                        '-L', '1' if os.environ.get('FIT_LAB_TX_LDPC') == '1' else '0',
                        f'127.0.0.1:{self.injector}'], 'control-tx.log')
            self.spawn([ssh_bridge], 'control-ssh.log')
        except Exception:
            self.close()
            raise

    def select_receiver(self, recovery, now):
        jobs = recovery.jobs.values()
        if not self.diversity_enabled:
            jobs = [j for j in jobs if j.index == 0]
        job = self.diversity.select(jobs, recovery.receivers, now)
        process = job.process if job else None
        if process is not self.tx_process:
            # An echo from the previous owner cannot certify the new path.
            self.pending.clear()
            self.last_reply = self.last_ping = 0
            self.state.update(state='waiting', rtt_ms=None)
        self.tx_job, self.tx_process = job, process
        self.state['tx_receiver'] = job.index + 1 if job else None
        self.state['tx_switches'] = self.diversity.switches
        self.state['tx_diversity_enabled'] = self.diversity_enabled

    def forward_encoded(self, data):
        job = self.tx_job
        if job is None or self.tx_process.poll() is not None:
            self.state['tx_dropped_no_receiver'] = self.state.get('tx_dropped_no_receiver', 0) + 1
            return
        try:
            self.encoded.sendto(data, ('127.0.0.1', job.tx_port))
            self.state['tx_forwarded'] = self.state.get('tx_forwarded', 0) + 1
        except OSError:
            self.state['tx_send_errors'] = self.state.get('tx_send_errors', 0) + 1

    def udp(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sockets.append(sock)
        sock.bind(('127.0.0.1', port))
        sock.setblocking(False)
        return sock

    def spawn(self, command, name):
        with (self.logs/name).open('ab') as log:
            child = subprocess.Popen(list(map(str, command)), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.children.append(child)
        self.commands.append((command, name))

    def send(self, data):
        try:
            address = str(self.socket_path) if sys.platform == 'darwin' else '\0' + str(self.socket_path)
            self.sender.sendto(data, address)
            return True
        except OSError:
            return False

    def poll(self, now):
        dead = next((i for i, child in enumerate(self.children) if child.poll() is not None), None)
        if dead is not None:
            self.last_reply = 0
            self.state.update(state='retrying', error='Повторный запуск обратного канала')
            if now >= self.retry_after:
                command, name = self.commands[dead]
                if name == 'control-tx.log':
                    self.socket_path.unlink(missing_ok=True)
                try:
                    with (self.logs/name).open('ab') as log:
                        self.children[dead] = subprocess.Popen(list(map(str, command)), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                except OSError:
                    pass
                self.restarts += 1
                self.state['restarts'] = self.restarts
                self.retry_after = now + min(30, 2 ** min(self.restarts, 5))
            return self.state
        if now-self.last_ping >= 1:
            self.sequence = (self.sequence + 1) % 65536
            if self.send(ping_packet(self.sequence, self.nonce)):
                self.pending[self.sequence] = now
                self.state['sent'] += 1
            self.last_ping = now
            expired = [seq for seq, stamp in self.pending.items() if now-stamp >= 5]
            for seq in expired:
                self.pending.pop(seq)
                self.echo_timeouts += 1
                self.echo_outcomes.append((now, False))
        for _ in range(32):
            try:
                data, _ = self.down.recvfrom(65535)
            except BlockingIOError:
                break
            replies = list(echo_replies(data, self.nonce))
            if len(replies) > 1:
                self.state['echo_batched_replies'] = self.state.get('echo_batched_replies', 0) + len(replies)
            for seq in replies:
                if seq in self.pending:
                    self.state['replies'] += 1
                    self.state['rtt_ms'] = round((now-self.pending.pop(seq))*1000, 1)
                    self.last_reply = now
                    self.echo_outcomes.append((now, True))
            ssh = ssh_records(data)
            if ssh:
                try:
                    self.gateway.sendto(ssh, ('127.0.0.1', 56551))
                except OSError:
                    pass
        # Bounded packets per pass; SSH/TCP supplies back pressure and retries.
        for _ in range(8):
            try:
                data, peer = self.gateway.recvfrom(8192)
            except BlockingIOError:
                break
            if peer == ('127.0.0.1', 56551):
                ssh = ssh_records(data, outbound=True)
                if ssh:
                    self.send(ssh)
        self.state['state'] = 'connected' if self.last_reply and now-self.last_reply < 3 else 'waiting'
        self.state.pop('error', None)
        self.state['last_reply_monotonic'] = self.last_reply
        outcomes = [ok for stamp, ok in self.echo_outcomes if now-stamp < 30]
        self.state.update(echo_timeouts=self.echo_timeouts, echo_window_samples=len(outcomes),
                          echo_loss_percent=round(100*(len(outcomes)-sum(outcomes))/len(outcomes), 1) if outcomes else None)
        return self.state

    def close(self, stop_processes=True):
        if stop_processes:
            from receiver.process_cleanup import stop_children
            stop_children(self.children)
        for sock in self.sockets:
            sock.close()
        self.socket_path.unlink(missing_ok=True)
