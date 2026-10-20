import threading
import sys
import types
import unittest
from unittest.mock import patch

import display_brightness
import input_injector
from brightness_worker import BrightnessWorker


class BrightnessInputTests(unittest.TestCase):
    def test_brightness_injection_returns_while_the_wmi_operation_is_blocked(self):
        entered = threading.Event()
        release = threading.Event()
        original = input_injector._IS_WINDOWS
        input_injector._IS_WINDOWS = False
        self.addCleanup(setattr, input_injector, "_IS_WINDOWS", original)
        self.addCleanup(release.set)

        def slow_adjust(_steps):
            entered.set()
            release.wait(2)

        with patch.object(display_brightness, "adjust", side_effect=slow_adjust):
            worker = threading.Thread(target=input_injector.inject_key, args=("brightness_up", True))
            worker.start()
            worker.join(0.2)
            self.assertFalse(worker.is_alive(), "brightness injection held the input reader")
            self.assertTrue(entered.wait(1), "brightness work was not started")

    def test_repeated_presses_coalesce_to_the_latest_net_target(self):
        entered = threading.Event()
        release = threading.Event()
        done = threading.Event()
        steps = []

        def adjust(target):
            steps.append(target)
            if len(steps) == 1:
                entered.set()
                release.wait(2)
            else:
                done.set()

        worker = BrightnessWorker(adjust)
        worker.submit(1)
        self.assertTrue(entered.wait(1))
        worker.submit(1)
        worker.submit(1)
        worker.submit(-1)
        worker.submit(1)
        release.set()
        self.assertTrue(done.wait(1))
        self.assertEqual(steps, [1, 2])


class DirectWmiTests(unittest.TestCase):
    def test_worker_thread_initialises_and_uninitialises_com_around_wmi(self):
        events = []
        pythoncom = types.ModuleType("pythoncom")
        pythoncom.CoInitialize = lambda: events.append("initialise")
        pythoncom.CoUninitialize = lambda: events.append("uninitialise")
        client = types.ModuleType("win32com.client")

        class Service:
            @staticmethod
            def ExecQuery(_query):
                events.append("query")
                return []

        class Locator:
            @staticmethod
            def ConnectServer(_host, _namespace):
                events.append("connect")
                return Service()

        client.Dispatch = lambda _name: Locator()
        win32com = types.ModuleType("win32com")
        win32com.__path__ = []
        with patch.dict(sys.modules, {
            "pythoncom": pythoncom,
            "win32com": win32com,
            "win32com.client": client,
        }):
            self.assertFalse(display_brightness.adjust(1))
        self.assertEqual(events[0], "initialise")
        self.assertEqual(events[-1], "uninitialise")

    def test_adjust_uses_wmi_com_and_steps_through_supported_levels(self):
        calls = []

        class Params:
            pass

        class MethodDefinition:
            class InParameters:
                @staticmethod
                def SpawnInstance_():
                    return Params()

        class Monitor:
            InstanceName = "panel"
            CurrentBrightness = 20
            Level = [0, 20, 40, 80]

            @staticmethod
            def Methods_(_name):
                return MethodDefinition()

            @staticmethod
            def ExecMethod_(_name, params):
                calls.append(params.Brightness)
                return type("Result", (), {"ReturnValue": 0})()

        class Service:
            @staticmethod
            def ExecQuery(query):
                return [Monitor()] if "WmiMonitorBrightness FROM" in query else [Monitor()]

        class Locator:
            @staticmethod
            def ConnectServer(_host, _namespace):
                return Service()

        self.assertTrue(display_brightness.adjust(2, dispatch=lambda _name: Locator()))
        self.assertEqual(calls, [80])


if __name__ == "__main__":
    unittest.main()
