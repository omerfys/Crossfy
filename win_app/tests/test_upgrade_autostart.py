"""The existing 1.5.1 global task must not silently lose its owner's enabled choice."""

import unittest
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import patch

import autostart_win
from test_autostart_win import FakeSchtasks, EXE

USER = r"SYNTHETIC\birch"


class UpgradeTasks(FakeSchtasks):
    def __init__(self, exists=True, enabled=True, owner=USER, fail=None):
        super().__init__(exists, fail)
        self.enabled = enabled
        self.owner = owner
        self.replacement_xml = None
        self.arguments = '--hidden'
        self.fail_delete = False

    def __call__(self, args):
        if args[1] == '/delete' and self.fail_delete:
            self.calls.append('/delete')
            return subprocess.CompletedProcess(args, 1, '', 'Access is denied')
        if args[1] == '/change' and '/disable' in args:
            self.enabled = False
        result = super().__call__(args)
        if args[1] == "/query" and result.returncode == 0:
            xml = autostart_win.task_xml(EXE, self.owner)
            if args[args.index("/tn") + 1] == "Beamer":
                xml = xml.replace('--hidden', self.arguments)
                if not self.enabled:
                    xml = xml.replace("<Enabled>true</Enabled>", "<Enabled>false</Enabled>")
            else:
                xml = self.xml or self.replacement_xml or xml
            return subprocess.CompletedProcess(args, 0, xml, "")
        return result


class UpgradeAutostartTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("installed_exe", EXE), ("can_run_for_current_user", True)):
            patcher = patch.object(autostart_win, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_enabled_1_5_1_task_stays_enabled_after_first_1_5_2_status_read(self):
        tasks = UpgradeTasks()
        self.assertTrue(autostart_win.is_enabled(tasks, USER))
        self.assertEqual(tasks.tasks, {autostart_win.task_name(USER)})
        self.assertLess(tasks.calls.index('/create'), tasks.calls.index('/delete'))

    def test_was_off_stays_off(self):
        for exists in (False, True):
            tasks = UpgradeTasks(exists=exists, enabled=False)
            self.assertFalse(autostart_win.is_enabled(tasks, USER))
            self.assertNotIn('/create', tasks.calls)

    def test_second_run_changes_nothing(self):
        tasks = UpgradeTasks()
        autostart_win.is_enabled(tasks, USER)
        tasks.calls.clear()
        self.assertTrue(autostart_win.is_enabled(tasks, USER))
        self.assertEqual(tasks.calls, ['/query', '/query'])

    def test_failed_registration_keeps_old_starter(self):
        tasks = UpgradeTasks(fail='Access is denied')
        with self.assertRaises(OSError):
            autostart_win.is_enabled(tasks, USER)
        self.assertEqual(tasks.tasks, {'Beamer'})
        self.assertNotIn('/delete', tasks.calls)

    def test_other_accounts_task_is_not_migrated(self):
        tasks = UpgradeTasks(owner=r'SYNTHETIC\other')
        self.assertFalse(autostart_win.is_enabled(tasks, USER))
        self.assertEqual(tasks.tasks, {'Beamer'})

    def test_unresolvable_account_is_not_migrated(self):
        tasks = UpgradeTasks(owner='S-1-5-21-unknown')
        with patch.object(autostart_win, '_user_sid', side_effect=OSError('no mapping')):
            self.assertFalse(autostart_win.is_enabled(tasks, USER))
        self.assertEqual(tasks.tasks, {'Beamer'})

    def test_sid_principal_is_migrated_for_its_owner(self):
        tasks = UpgradeTasks(owner='S-1-5-21-123-456-789-1001')
        with patch.object(autostart_win, '_user_sid', return_value=tasks.owner):
            self.assertTrue(autostart_win.is_enabled(tasks, USER))
        self.assertEqual(tasks.tasks, {autostart_win.task_name(USER)})

    def test_existing_per_user_task_is_not_registered_again(self):
        tasks = UpgradeTasks()
        tasks.tasks.add(autostart_win.task_name(USER))
        self.assertTrue(autostart_win.is_enabled(tasks, USER))
        self.assertNotIn('/create', tasks.calls)
        self.assertNotIn('Beamer', tasks.tasks)

    def test_broken_replacement_is_repaired_before_legacy_deletion(self):
        valid = autostart_win.task_xml(EXE, USER)
        for broken in (
            valid.replace(
                '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n    <Enabled>true</Enabled>',
                '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n    <Enabled>false</Enabled>'),
            valid.replace(EXE, r'C:\Missing\Beamer.exe'),
            valid.replace('<LogonTrigger>\n      <Enabled>true</Enabled>', '<LogonTrigger>\n      <Enabled>false</Enabled>'),
            valid.replace('<LogonTrigger>', '<TimeTrigger>').replace('</LogonTrigger>', '</TimeTrigger>'),
        ):
            with self.subTest(xml=broken):
                tasks = UpgradeTasks()
                tasks.tasks.add(autostart_win.task_name(USER))
                tasks.replacement_xml = broken
                self.assertTrue(autostart_win.is_enabled(tasks, USER))
                self.assertIn('/create', tasks.calls)
                self.assertLess(tasks.calls.index('/create'), tasks.calls.index('/delete'))
                self.assertEqual(tasks.tasks, {autostart_win.task_name(USER)})

    def test_failed_replacement_repair_keeps_legacy_starter(self):
        tasks = UpgradeTasks(fail='Access is denied')
        tasks.tasks.add(autostart_win.task_name(USER))
        tasks.replacement_xml = autostart_win.task_xml(r'C:\Missing\Beamer.exe', USER)
        with self.assertRaises(OSError):
            autostart_win.is_enabled(tasks, USER)
        self.assertIn('Beamer', tasks.tasks)
        self.assertNotIn('/delete', tasks.calls)

    def test_migration_preserves_legacy_config_arguments(self):
        tasks = UpgradeTasks()
        tasks.arguments = '--hidden --config "C:\\User Data\\a &amp; b.json"'
        self.assertTrue(autostart_win.is_enabled(tasks, USER))
        root = ET.fromstring(tasks.xml)
        self.assertEqual(root.findtext('{*}Actions/{*}Exec/{*}Arguments'),
                         '--hidden --config "C:\\User Data\\a & b.json"')

    def test_existing_replacement_keeps_legacy_config_arguments(self):
        tasks = UpgradeTasks()
        tasks.tasks.add(autostart_win.task_name(USER))
        tasks.arguments = '--hidden --config "C:\\User Data\\custom.json"'
        self.assertTrue(autostart_win.is_enabled(tasks, USER))
        self.assertIsNotNone(tasks.xml)
        root = ET.fromstring(tasks.xml)
        self.assertEqual(root.findtext('{*}Actions/{*}Exec/{*}Arguments'),
                         '--hidden --config "C:\\User Data\\custom.json"')

    def test_failed_legacy_delete_leaves_one_enabled_starter_and_retries(self):
        tasks = UpgradeTasks()
        tasks.fail_delete = True
        with self.assertRaises(OSError):
            autostart_win.is_enabled(tasks, USER)
        self.assertEqual(tasks.tasks, {'Beamer', autostart_win.task_name(USER)})
        self.assertFalse(tasks.enabled)
        tasks.fail_delete = False
        tasks.calls.clear()
        self.assertTrue(autostart_win.is_enabled(tasks, USER))
        self.assertEqual(tasks.tasks, {autostart_win.task_name(USER)})
        self.assertNotIn('/create', tasks.calls)

    def test_wrong_executable_leaves_legacy_task_untouched(self):
        tasks = UpgradeTasks()
        with patch.object(autostart_win, 'installed_exe', return_value=r'C:\Other\Beamer.exe'):
            self.assertFalse(autostart_win.is_enabled(tasks, USER))
        self.assertEqual(tasks.tasks, {'Beamer'})


if __name__ == '__main__':
    unittest.main()
