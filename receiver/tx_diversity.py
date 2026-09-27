"""One TX owner, held until its native process has actually stopped.

Both adapters stay in RX/TX bridge mode. Only the selected bridge receives
encoded command datagrams; choosing it never restarts the surviving receiver.
"""


class TxDiversity:
    def __init__(self, observation_seconds=1.5):
        self.owner = None
        self.process = None
        self.last_index = None
        self.switches = 0
        self.observation_seconds = observation_seconds
        self.first_ready = None

    def select(self, jobs, receivers, now):
        if self.process is not None and self.process.poll() is None:
            job = self.owner
            # A disconnected/hung bridge may still have queued TX. Do not
            # feed either adapter until shutdown of that bridge is confirmed.
            if (job.process is self.process and job.phase == 'receiving'
                    and not job.removing and not job.recovering):
                return job
            return None

        self.owner = self.process = None
        candidates = []
        for job in jobs:
            if (job.index is None or job.phase != 'receiving' or job.removing
                    or job.recovering or job.process is None
                    or job.process.poll() is not None):
                continue
            last = receivers[job.index]['last_frame_monotonic']
            # Commands must also work when the camera's video service is off.
            # The native ready marker certifies completed radio initialization.
            if not job.tx_ready and (last <= 0 or now - last >= 2):
                continue
            candidates.append(job)
        if not candidates:
            return None
        if self.first_ready is None:
            self.first_ready = now
        # Observe actual reception once at startup. A strong RSSI alone can
        # hide a poorly receiving adapter. Later handovers retain the strict
        # old-process-exited rule above and do not delay failover.
        if self.last_index is None and now - self.first_ready < self.observation_seconds:
            return None
        def rate(job):
            state = receivers[job.index]
            return float(state.get('packets_per_second', 0)) if now - state['last_frame_monotonic'] < 2 else 0
        best = max(map(rate, candidates))
        candidates = [job for job in candidates if rate(job) >= best * .8]
        def quality(job):
            state = receivers[job.index]
            rssi = state.get('rssi_dbm') if rate(job) > 0 else None
            return (rssi if isinstance(rssi, (int, float)) else -200, rate(job), -job.index)
        for job in sorted(candidates, key=quality, reverse=True):
            if self.last_index is not None and job.index != self.last_index:
                self.switches += 1
            self.last_index = job.index
            self.owner, self.process = job, job.process
            return job
        return None
