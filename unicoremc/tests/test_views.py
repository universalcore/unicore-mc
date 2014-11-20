import json
import os
import shutil
import pytest
import responses

from django.conf import settings
from django.test.client import Client
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User

from git import Repo
from elasticgit.manager import StorageManager

from unicoremc.models import Project, Localisation
from unicoremc.manager import DbManager
from unicore.content.models import Category, Page
from unicoremc.tests.base import UnicoremcTestCase

from mock import patch


@pytest.mark.django_db
class ViewsTestCase(UnicoremcTestCase):
    fixtures = ['test_users.json', 'test_social_auth.json']

    def setUp(self):
        self.client = Client()
        self.client.login(username='testuser', password='test')

        workdir = os.path.join(settings.CMS_REPO_PATH, 'test-source-repo')
        self.source_repo_sm = StorageManager(Repo.init(workdir))
        self.source_repo_sm.create_storage()
        self.source_repo_sm.write_config('user', {
            'name': 'testuser',
            'email': 'test@email.com',
        })

        workdir = os.path.join(settings.CMS_REPO_PATH, 'test-base-repo')
        self.base_repo_sm = StorageManager(Repo.init(workdir))
        self.base_repo_sm.create_storage()
        self.base_repo_sm.write_config('user', {
            'name': 'testuser',
            'email': 'test@email.com',
        })

        self.base_repo_sm.store_data(
            'sample.txt', 'This is a sample file!', 'Create sample file')

        self.addCleanup(self.source_repo_sm.destroy_storage)
        self.addCleanup(self.base_repo_sm.destroy_storage)

    @responses.activate
    def test_create_new_project(self):
        self.client.login(username='testuser2', password='test')

        self.mock_create_repo()
        self.mock_create_webhook()

        data = {
            'app_type': 'ffl',
            'base_repo': self.base_repo_sm.repo.git_dir,
            'country': 'ZA',
            'access_token': 'some-access-token',
            'user_id': 1,
            'team_id': 1
        }

        with patch.object(DbManager, 'call_subprocess') as mock_subprocess:
            mock_subprocess.return_value = None
            response = self.client.post(reverse('start_new_project'), data)

        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(json.loads(response.content), {
            'success': True
        })

        project = Project.objects.all()[0]
        self.assertEqual(project.state, 'done')

        workspace = self.mk_workspace()
        workspace.setup('Test Kees', 'kees@example.org')
        workspace.setup_mapping(Category)
        workspace.setup_mapping(Page)

        cat = Category({
            'title': 'Some title',
            'slug': 'some-slug'
        })
        workspace.save(cat, 'Saving a Category')

        page = Page({
            'title': 'Some page title',
            'slug': 'some-page-slug'
        })
        workspace.save(page, 'Saving a Page')

        workspace.refresh_index()

        self.assertEqual(
            workspace.S(Category).count(), 1)
        self.assertEqual(
            workspace.S(Page).count(), 1)

        self.addCleanup(lambda: shutil.rmtree(
            os.path.join(settings.CMS_REPO_PATH, 'ffl-za')))
        self.addCleanup(lambda: shutil.rmtree(
            os.path.join(settings.FRONTEND_REPO_PATH, 'ffl-za')))

    def test_language_updates(self):
        self.client.login(username='testuser2', password='test')

        self.mock_create_repo()
        self.mock_create_webhook()

        Localisation._for('eng_UK')
        Localisation._for('swa_TZ')

        data = {
            'app_type': 'ffl',
            'base_repo': self.base_repo_sm.repo.git_dir,
            'country': 'ZA',
            'access_token': 'some-access-token',
            'user_id': 1,
            'team_id': 1
        }

        self.client.post(reverse('start_new_project'), data)
        project = Project.objects.all()[0]

        resp = self.client.get(reverse('advanced', args=[project.id]))

        self.assertContains(resp, 'English')
        self.assertContains(resp, 'Swahili')

        self.assertEqual(project.available_languages.count(), 0)

        frontend_supervisor_config_path = os.path.join(
            settings.SUPERVISOR_CONFIGS_PATH,
            'frontend_ffl_za.conf')
        cms_supervisor_config_path = os.path.join(
            settings.SUPERVISOR_CONFIGS_PATH,
            'cms_ffl_za.conf')

        with open(frontend_supervisor_config_path, "r") as config_file:
            data = config_file.read()
        self.assertTrue("UNICORE_PROJECT_VERSION=0" in data)

        with open(cms_supervisor_config_path, "r") as config_file:
            data = config_file.read()
        self.assertTrue("UNICORE_PROJECT_VERSION=0" in data)

        resp = self.client.post(
            reverse('advanced', args=[project.id]),
            {'available_languages': [1, 2]})

        project = Project.objects.get(pk=project.id)
        self.assertEqual(project.available_languages.count(), 2)

        frontend_settings_path = os.path.join(
            settings.FRONTEND_SETTINGS_OUTPUT_PATH,
            'ffl.production.za.ini')

        with open(frontend_settings_path, "r") as config_file:
            data = config_file.read()

        self.assertTrue(
            "[(u'eng_UK', u'English'), "
            "(u'swa_TZ', u'Swahili')]" in data)

        with open(frontend_supervisor_config_path, "r") as config_file:
            data = config_file.read()
        self.assertTrue("UNICORE_PROJECT_VERSION=1" in data)

        with open(cms_supervisor_config_path, "r") as config_file:
            data = config_file.read()
        self.assertTrue("UNICORE_PROJECT_VERSION=1" in data)

    def test_view_only_on_homepage(self):
        resp = self.client.get(reverse('home'))
        self.assertNotContains(resp, 'Start new project')
        self.assertNotContains(resp, 'edit')

        self.client.login(username='testuser2', password='test')

        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'Start new project')
        self.assertContains(resp, 'edit')

    def test_staff_access_required(self):
        p = Project(
            app_type='ffl',
            base_repo_url='http://some-git-repo.com',
            country='ZA',
            owner=User.objects.get(pk=2))
        p.save()

        resp = self.client.get(reverse('new_project'))
        self.assertEqual(resp.status_code, 302)

        resp = self.client.get(reverse('start_new_project'))
        self.assertEqual(resp.status_code, 302)

        resp = self.client.get(reverse('advanced', args=[1]))
        self.assertEqual(resp.status_code, 302)
