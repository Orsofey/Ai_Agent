"""Native microphone capture (works when the window is hidden or another app is active)."""
import logging
import queue

import numpy as np

from .audio import SAMPLE_RATE, resample
from .vad import FRAME

log = logging.getLogger(__name__)


def list_devices():
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default = sd.default.device[0] if sd.default.device else None
    except Exception:
        return []
    result, seen = [], set()
    for index, device in enumerate(devices):
        if device.get('max_input_channels', 0) < 1:
            continue
        name = device['name']
        if name in seen:
            continue
        seen.add(name)
        result.append({'id': name, 'label': name, 'default': index == default})
    return result


def find_device(name):
    if not name:
        return None
    import sounddevice as sd
    for index, device in enumerate(sd.query_devices()):
        if device.get('max_input_channels', 0) > 0 and device['name'] == name:
            return index
    for index, device in enumerate(sd.query_devices()):
        if device.get('max_input_channels', 0) > 0 and name.casefold() in device['name'].casefold():
            return index
    return None


class Microphone:
    def __init__(self, device_name=''):
        self.device_name = device_name
        self.queue = queue.Queue(maxsize=400)
        self.stream = None
        self.rate = SAMPLE_RATE
        self.buffer = np.zeros(0, dtype=np.float32)
        self.level = 0.0

    def _callback(self, data, frames, time_info, status):
        try:
            self.queue.put_nowait(data[:, 0].copy())
        except queue.Full:
            pass  # обработка отстаёт — пропускаем кадр, а не копим задержку

    def open(self):
        import sounddevice as sd
        device = find_device(self.device_name)
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32',
                                         blocksize=FRAME, device=device, callback=self._callback)
            self.rate = SAMPLE_RATE
        except Exception:
            info = sd.query_devices(device if device is not None else sd.default.device[0])
            self.rate = int(info['default_samplerate'])
            self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype='float32',
                                         blocksize=int(FRAME * self.rate / SAMPLE_RATE), device=device,
                                         callback=self._callback)
        self.stream.start()
        return self

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def frames(self, stop_event):
        """Генератор кадров по 512 отсчётов 16 кГц."""
        while not stop_event.is_set():
            try:
                chunk = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.rate != SAMPLE_RATE:
                chunk = resample(chunk, self.rate)
            self.buffer = np.concatenate([self.buffer, chunk])
            while self.buffer.size >= FRAME:
                frame, self.buffer = self.buffer[:FRAME], self.buffer[FRAME:]
                self.level = float(np.sqrt(np.mean(frame * frame)))
                yield frame
