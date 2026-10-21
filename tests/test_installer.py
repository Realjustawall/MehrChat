"""Installer client-build recovery; never starts services or real GitHub jobs."""
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform.startswith('linux'), 'Ubuntu setup uses pwd')
class ClientBuildSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'deploy/setup-ubuntu.py'
        spec = importlib.util.spec_from_file_location('ubuntu_setup', path)
        cls.setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.setup)

    def invoke(self, statuses, answer=True, installed=True):
        output = io.StringIO()
        with patch.object(self.setup, 'yes', return_value=answer), \
             patch.object(self.setup.shutil, 'which', return_value='/usr/bin/gh' if installed else None), \
             patch.object(self.setup.subprocess, 'run', side_effect=[Mock(returncode=n) for n in statuses]) as run, \
             patch('sys.stdout', output):
            self.setup.build_clients(Path('/var/lib/mehrchat/client-profile.json'))
        return run, output.getvalue()

    def test_authenticated_setup_builds_and_downloads(self):
        run, output = self.invoke([0, 0])
        command = run.call_args_list[-1].args[0]
        self.assertIn('/var/lib/mehrchat/client-profile.json', command)
        self.assertEqual(command[-1], '/var/lib/mehrchat/dedicated-clients')
        self.assertIn('downloaded', output)

    def test_device_login_failure_preserves_relay_and_prints_resume(self):
        run, output = self.invoke([1, 1])
        self.assertEqual(run.call_count, 2)
        self.assertIn('--web', run.call_args_list[1].args[0])
        self.assertIn('relay remains running', output)
        self.assertIn('Resume client build', output)

    def test_failed_build_can_be_resumed(self):
        _, output = self.invoke([0, 1])
        self.assertIn('did not finish successfully', output)
        self.assertIn('Resume client build', output)

    def test_skip_does_not_contact_github(self):
        run, _ = self.invoke([], answer=False)
        run.assert_not_called()

    def test_missing_cli_prints_recovery_command(self):
        run, output = self.invoke([], installed=False)
        run.assert_not_called()
        self.assertIn('Resume client build', output)
