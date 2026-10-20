import unittest

from core import feature_flags


class ShippedDefaultsTests(unittest.TestCase):
    def test_phone_pairing_is_hidden_by_default(self):
        # Phone pairing stays hidden until the phone apps ship.
        self.assertIs(feature_flags.PAIRING_QR_VISIBLE, False)
