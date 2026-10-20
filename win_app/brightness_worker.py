"""Run Windows display brightness changes away from the input reader."""

import threading


class BrightnessWorker:
    def __init__(self, adjust):
        self._adjust = adjust
        self._condition = threading.Condition()
        self._steps = 0
        self._thread = None

    def submit(self, delta):
        steps = 1 if delta > 0 else -1 if delta < 0 else 0
        if not steps:
            return
        with self._condition:
            self._steps += steps
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="Beamer-brightness", daemon=True)
                self._thread.start()
            self._condition.notify()

    def _run(self):
        while True:
            with self._condition:
                if self._steps == 0:
                    self._thread = None
                    return
                steps, self._steps = self._steps, 0
            self._adjust(steps)


def _adjust(steps):
    from display_brightness import adjust

    adjust(steps)


_worker = BrightnessWorker(_adjust)


def submit(delta):
    _worker.submit(delta)
