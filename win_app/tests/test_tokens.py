from pathlib import Path
import unittest

WIN_APP = Path(__file__).resolve().parent.parent
ROOT_TOKENS = WIN_APP.parent / "tokens.py"


class TokensCopyTest(unittest.TestCase):
    @unittest.skipUnless(ROOT_TOKENS.exists(), "no repo root beside win_app, as in an installed layout")
    def test_win_app_copy_is_byte_identical_to_the_root(self):
        self.assertEqual(
            (WIN_APP / "tokens.py").read_bytes(),
            ROOT_TOKENS.read_bytes(),
            "win_app/tokens.py has drifted from tokens.py; copy the root file across",
        )


if __name__ == "__main__":
    unittest.main()
