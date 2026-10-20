import threading
import time
import unittest

from core.idle_pointer import IdlePointer


class Pointer:
    def __init__(self):
        self.at = (100, 100)
        self.calls = []
        self.shown = threading.Event()

    def hide(self):
        self.calls.append("hide")

    def show(self):
        self.calls.append("show")
        self.shown.set()

    def position(self):
        return self.at


def wait_for(predicate, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class IdlePointerTests(unittest.TestCase):
    def setUp(self):
        self.pointer = Pointer()
        self.idle = IdlePointer(
            self.pointer.hide, self.pointer.show, self.pointer.position, poll_seconds=0.01, settle_seconds=0.05
        )

    def test_hidden_until_the_pointer_moves(self):
        self.idle.driver_left()
        self.assertEqual(self.pointer.calls, ["hide"])
        time.sleep(0.1)
        self.assertEqual(self.pointer.calls, ["hide"])
        self.pointer.at = (101, 100)
        self.assertTrue(self.pointer.shown.wait(1))
        self.assertTrue(wait_for(lambda: not self.idle.hidden))
        self.assertEqual(self.pointer.calls, ["hide", "show"])

    def test_a_move_while_settling_is_the_drivers_and_does_not_show_it(self):
        self.idle.driver_left()
        self.pointer.at = (140, 90)
        time.sleep(0.15)
        self.assertEqual(self.pointer.calls, ["hide"])
        self.assertTrue(self.idle.hidden)
        self.idle.cancel()

    def test_a_driver_arriving_shows_it_once(self):
        self.idle.driver_left()
        self.idle.cancel()
        self.idle.cancel()
        time.sleep(0.1)
        self.assertEqual(self.pointer.calls, ["hide", "show"])

    def test_leaving_twice_hides_once(self):
        self.idle.driver_left()
        self.idle.driver_left()
        self.assertEqual(self.pointer.calls, ["hide"])
        self.idle.cancel()

    def test_hide_again_after_a_cancel_is_watched_afresh(self):
        self.idle.driver_left()
        self.idle.cancel()
        self.idle.driver_left()
        time.sleep(0.1)
        self.pointer.at = (0, 0)
        self.assertTrue(wait_for(lambda: self.pointer.calls == ["hide", "show", "hide", "show"]))

    def test_an_unreadable_pointer_is_shown_rather_than_left_hidden(self):
        def broken():
            raise OSError("gone")

        idle = IdlePointer(self.pointer.hide, self.pointer.show, broken, poll_seconds=0.01, settle_seconds=0.01)
        idle.driver_left()
        self.assertTrue(self.pointer.shown.wait(1))
        self.assertFalse(wait_for(lambda: idle.hidden, 0.05))

    def test_a_failed_hide_watches_nothing(self):
        def refuse():
            raise OSError("no")

        idle = IdlePointer(refuse, self.pointer.show, self.pointer.position)
        idle.driver_left()
        self.assertFalse(idle.hidden)
        idle.cancel()
        self.assertEqual(self.pointer.calls, [])


if __name__ == "__main__":
    unittest.main()
