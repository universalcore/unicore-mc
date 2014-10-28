import httpretty
import os

from django.test import TestCase
from django.conf import settings

from unicoremc.manager import SettingsManager
from unicoremc.models import Localisation


@httpretty.activate
class SettingsManagerTestCase(TestCase):

    def test_write_frontend_settings(self):
        english = Localisation._for('eng_UK')
        afrikaans = Localisation._for('swh_TZ')
        cm = SettingsManager()
        cm.write_frontend_settings(
            'ffl', 'za', 'http://some.repo.com/.git', [english, afrikaans],
            '/path/to/repo/ffl_za/')

        frontend_settings_path = os.path.join(
            settings.FRONTEND_SETTINGS_OUTPUT_PATH,
            'ffl.production.za.ini')

        socket_path = os.path.join(
            settings.SOCKETS_PATH,
            'ffl.za.socket')

        self.assertTrue(os.path.exists(frontend_settings_path))

        with open(frontend_settings_path, "r") as config_file:
            data = config_file.read()

        self.addCleanup(lambda: os.remove(frontend_settings_path))

        self.assertTrue('egg:unicore-cms-ffl' in data)
        self.assertTrue(
            "[('eng_UK', 'English (United Kingdom)')"
            ", ('swh_TZ', 'Swahili (Tanzania)')]" in data)
        self.assertTrue('/ffl_za/' in data)
        self.assertTrue('http://some.repo.com/.git' in data)
        self.assertTrue(socket_path in data)

    def test_write_cms_settings(self):
        cm = SettingsManager()
        cm.write_cms_settings(
            'ffl', 'za', 'http://some.repo.com/.git')

        cms_settings_path = os.path.join(
            settings.CMS_SETTINGS_OUTPUT_PATH,
            'ffl_za_settings.py')

        self.assertTrue(os.path.exists(cms_settings_path))

        with open(cms_settings_path, "r") as config_file:
            data = config_file.read()

        self.addCleanup(lambda: os.remove(cms_settings_path))

        self.assertTrue('django_cms_ffl_za' in data)
        self.assertTrue(
            "/var/praekelt/unicore-cms-django/project/ffl_za" in data)
        self.assertTrue('http://some.repo.com/.git' in data)