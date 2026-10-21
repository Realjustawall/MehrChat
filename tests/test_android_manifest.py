"""The isolated service must be an application child, never an attribute."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from scripts.android_hook import configure_manifest,ANDROID,NAME,SERVICE

class AndroidManifest(unittest.TestCase):
    def test_assembler_keeps_activity_permissions_and_one_isolated_service(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'AndroidManifest.xml'
            path.write_text('<manifest xmlns:android="'+ANDROID+'"><uses-permission android:name="android.permission.INTERNET"/><application android:allowBackup="false"><activity android:name="org.kivy.android.PythonActivity" android:exported="true"/></application></manifest>',encoding='utf-8')
            configure_manifest(path);configure_manifest(path)
            root=ET.parse(path).getroot();app=root.find('application')
            self.assertEqual(root.find('uses-permission').get(NAME),'android.permission.INTERNET')
            self.assertEqual(app.find('activity').get(NAME),'org.kivy.android.PythonActivity')
            self.assertEqual(app.get('{'+ANDROID+'}allowBackup'),'false')
            services=app.findall('service');self.assertEqual(len(services),1)
            self.assertEqual(services[0].get(NAME),SERVICE)
            self.assertEqual(services[0].get('{'+ANDROID+'}isolatedProcess'),'true')
            self.assertEqual(services[0].get('{'+ANDROID+'}exported'),'false')
