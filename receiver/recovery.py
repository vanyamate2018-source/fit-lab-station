"""Independent USB receiver recovery; no process or USB operation blocks tick()."""
from dataclasses import dataclass, field
import uuid

RX_MACS = ("00:13:ef:f2:13:c1", "88:e6:28:6b:ca:ff")


@dataclass
class Job:
    device: dict
    index: int | None = None
    process: object = None
    phase: str = "new"
    attempt: int = 0
    failures: int = 0
    next_retry: float = 0
    started: float = 0
    profile: dict | None = None
    tx_port: int | None = None
    tx_ready: bool = False
    tuning: dict | None = None
    removing: bool = False
    recovering: bool = False
    recover_after: float = 0
    generation: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class RadioRecovery:
    def __init__(self, backend, notify=lambda *_: None):
        self.backend = backend
        self.notify = notify
        self.jobs = {}
        self.devices = []
        self.closed = False
        self.last_assisted_recovery = -30.0
        self.receivers = [dict(index=i, mac=mac, connection="disconnected", input_frames=0,
                               forwarded=0, dropped=0, last_frame_monotonic=0, restarts=0)
                          for i, mac in enumerate(RX_MACS)]

    @staticmethod
    def identity(device):
        return device["location"], device["address"]

    def tick(self, now, devices=None):
        if self.closed:
            return
        if devices is not None:
            self.devices = devices
        present = {self.identity(d): d for d in self.devices}
        for key, job in list(self.jobs.items()):
            if key not in present and not job.removing:
                job.removing = True
                job.started = now
                if job.process and job.process.poll() is None:
                    job.process.terminate()
                if job.index is not None:
                    self._state(job, "disconnected")
                    self.notify(f"RX{job.index + 1} отключён")
            if job.removing:
                if job.process and job.process.poll() is None:
                    if now - job.started > .75:
                        job.process.kill()
                    continue
                self.backend.finish(job)
                del self.jobs[key]
                continue
            if job.recovering:
                if job.process and job.process.poll() is None:
                    if now - job.started > 3:
                        job.process.kill()
                    continue
                job.recovering = False
            if job.process is not None:
                code = job.process.poll()
                if code is None:
                    if job.phase == 'retuning' and now - job.started > 3:
                        job.process.kill()
                    if job.phase == "preparing" and now - job.started > 45:
                        job.process.kill()
                    elif job.phase == "receiving" and job.index is not None:
                        item = self.receivers[job.index]
                        if not job.tx_ready and hasattr(self.backend, 'ready'):
                            job.tx_ready = self.backend.ready(job)
                        last = item["last_frame_monotonic"]
                        if now - max(last, job.started) > 2:
                            item["connection"] = "waiting"
                        # Silence alone can mean the camera went out of range.
                        # Recover only this RX when its peer proves the stream
                        # is still on-air. Never reset both on signal loss.
                        peer_live = any(i != job.index and r["last_frame_monotonic"] > 0
                                        and now - r["last_frame_monotonic"] < 1
                                        for i, r in enumerate(self.receivers))
                        if (getattr(self.backend, 'assisted_recovery', True) and peer_live and now - max(last, job.started) > 8
                                and now >= job.recover_after
                                and now - self.last_assisted_recovery >= 30):
                            job.process.terminate()
                            job.recovering, job.started = True, now
                            job.recover_after = now + 60
                            self.last_assisted_recovery = now
                            self._state(job, "retrying")
                            item["recovery_reason"] = "silent_while_peer_receives"
                            self.notify(f"RX{job.index + 1}: восстановление · второй RX продолжает приём")
                    continue
                job.process = None
                try:
                    if job.phase == 'retuning' and job.profile:
                        job.attempt += 1
                        job.process = self.backend.receive(job)
                        job.phase, job.started = 'receiving', now
                        self.receivers[job.index]['process_id'] = getattr(job.process, 'pid', None)
                        self._state(job, 'waiting')
                        continue
                    if job.phase == "preparing" and code == 0:
                        mac, profile = self.backend.profile(job)
                        if mac not in RX_MACS:
                            job.phase = "unsupported"
                            self.notify("Подключён непроверенный USB-приёмник")
                            continue
                        index = RX_MACS.index(mac)
                        if any(other is not job and other.index == index and other.phase == "receiving"
                               for other in self.jobs.values()):
                            raise ValueError("Повторная идентичность USB-приёмника")
                        job.index, job.profile = index, profile
                        item = self.receivers[index]
                        initializations = item.get("initializations", 0) + 1
                        item.update(job.device, profile=profile, initializations=initializations,
                                    restarts=initializations - 1)
                        job.process = self.backend.receive(job)
                        item['process_id'] = getattr(job.process, 'pid', None)
                        job.phase, job.started = "receiving", now
                        self._state(job, "waiting")
                        self.notify(f"RX{index + 1} подключён" if job.attempt == 1 else f"RX{index + 1} восстановлен")
                        continue
                    self.backend.finish(job)
                    self._retry(job, now)
                except (OSError, ValueError, KeyError) as exc:
                    self._retry(job, now)
                    self.notify(str(exc))
            if job.phase in ("new", "retrying") and now >= job.next_retry:
                try:
                    job.attempt += 1
                    job.process = self.backend.prepare(job)
                    job.phase, job.started = "preparing", now
                    self._state(job, "initializing")
                except OSError:
                    self._retry(job, now)
        # Delay reuse of a USB location until its previous process has exited.
        occupied_locations = {job.device["location"] for job in self.jobs.values()}
        for key, device in present.items():
            if key not in self.jobs and device["location"] not in occupied_locations:
                self.jobs[key] = Job(dict(device))
                occupied_locations.add(device["location"])

    def _state(self, job, state):
        if job.index is not None:
            self.receivers[job.index].update(connection=state, last_frame_monotonic=0,
                                              rssi_dbm=None, snr_db=None)
            if state != 'waiting':
                self.receivers[job.index]['process_id'] = None

    def _retry(self, job, now):
        job.tx_ready = False
        job.failures += 1
        job.phase = "retrying"
        job.next_retry = now + min(30, .5 * 2 ** min(job.failures - 1, 6))
        self._state(job, "retrying")
        if job.failures == 1:
            self.notify(f"RX{job.index + 1}: переподключение" if job.index is not None else "Повторная проверка USB-приёмника")

    def received(self, index, now):
        job = next((j for j in self.jobs.values() if j.index == index and j.phase == "receiving" and not j.removing), None)
        if job is None:
            return False
        if now - job.started > 10:
            job.failures = 0
        item = self.receivers[index]
        item.update(connection="receiving", last_frame_monotonic=now)
        item["input_frames"] += 1
        return True

    def close(self):
        self.closed = True
        for job in self.jobs.values():
            if job.process and job.process.poll() is None:
                job.process.terminate()

    def retune(self, job, tuning, now):
        """Discovery only: change one adapter, reusing its verified EFUSE profile."""
        if job.removing or job.phase != 'receiving' or job.tuning == tuning:
            return False
        job.tuning = dict(tuning)
        job.tx_ready = False
        job.phase, job.started = 'retuning', now
        self._state(job, 'initializing')
        if job.process and job.process.poll() is None:
            job.process.terminate()
        return True
