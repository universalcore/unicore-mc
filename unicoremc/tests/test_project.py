import re
import responses
import pytest
import os
import json
import shutil

from unittest import skip

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.signals import post_save

from git import Repo
import mock

from unicoremc.models import (
    Project, Localisation, AppType, publish_to_websocket)
from unicoremc import exceptions
from unicoremc.tests.base import UnicoremcTestCase

from unicore.content.models import (
    Category, Page, Localisation as EGLocalisation)


@pytest.mark.django_db
class ProjectTestCase(UnicoremcTestCase):
    fixtures = ['test_users.json', 'test_social_auth.json']

    def setUp(self):
        self.mk_test_repos()
        self.user = User.objects.get(username='testuser')
        post_save.disconnect(publish_to_websocket, sender=Project)

    @responses.activate
    def test_create_repo_state(self):
        self.mock_create_repo()

        p = self.mk_project()
        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')

        self.assertEquals(
            p.own_repo().url,
            self.source_repo_sm.repo.git_dir)
        self.assertEquals(p.state, 'repo_created')
        self.assertEqual(len(responses.calls), 1)
        self.assertIn('Authorization', responses.calls[0].request.headers)

    @responses.activate
    def test_create_repo_bad_response(self):
        self.mock_create_repo(status=404, data={'message': 'Not authorized'})

        p = self.mk_project()

        with self.assertRaises(exceptions.GithubApiException):
            pw = p.get_website_manager().workflow
            pw.take_action('create_repo')

        self.assertEquals(p.state, 'initial')

    @responses.activate
    def test_clone_repo(self):
        self.mock_create_repo()

        p = self.mk_project()

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')

        self.assertEquals(p.state, 'repo_cloned')
        self.assertTrue(os.path.isdir(os.path.join(p.repo_path(), '.git')))
        self.assertFalse(
            os.path.exists(os.path.join(p.repo_path(), 'README.md')))
        self.assertTrue(
            os.path.exists(os.path.join(p.repo_path(), 'text.txt')))

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @responses.activate
    def test_create_remotes_repo(self):
        self.mock_create_repo()

        p = self.mk_project(repo={'base_url': self.base_repo_sm.repo.git_dir})

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')

        self.assertEquals(p.state, 'remote_created')
        self.assertTrue(os.path.isdir(os.path.join(p.repo_path(), '.git')))

        repo = Repo(p.repo_path())
        self.assertEquals(len(repo.remotes), 2)
        self.assertEquals(
            repo.remote(name='upstream').url,
            self.base_repo_sm.repo.git_dir)

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @skip("slow test that connects to github")
    def test_create_remotes_repo_from_github(self):  # pragma: no cover
        self.mock_create_repo()

        p = self.mk_project(repo={
            'base_url': 'git://github.com/universalcore/'
                        'unicore-cms-content-gem-tanzania.git'})

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')

        self.assertEquals(p.state, 'remote_merged')
        self.assertTrue(os.path.isdir(os.path.join(p.repo_path(), '.git')))
        self.assertTrue(
            os.path.exists(os.path.join(p.repo_path(), 'README.md')))

        repo = Repo(p.repo_path())
        self.assertEquals(len(repo.remotes), 2)
        self.assertEquals(
            repo.remote(name='upstream').url,
            ('git://github.com/universalcore/'
             'unicore-cms-content-gem-tanzania.git'))

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @responses.activate
    def test_merge_remote_repo(self):
        self.mock_create_repo()

        p = self.mk_project(repo={'base_url': self.base_repo_sm.repo.git_dir})

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')

        self.assertEquals(p.state, 'remote_merged')
        self.assertTrue(os.path.isdir(os.path.join(p.repo_path(), '.git')))
        self.assertTrue(
            os.path.exists(os.path.join(p.repo_path(), 'sample.txt')))

        repo = Repo(p.repo_path())

        workspace = self.mk_workspace(
            working_dir=settings.CMS_REPO_PATH,
            name='ffl-za',
            index_prefix='unicore_cms_ffl_za')

        self.assertEqual(workspace.S(Category).count(), 1)
        self.assertEqual(workspace.S(Page).count(), 1)
        self.assertEqual(workspace.S(EGLocalisation).count(), 1)

        self.assertEquals(len(repo.remotes), 2)
        self.assertEquals(
            repo.remote(name='upstream').url,
            self.base_repo_sm.repo.git_dir)

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @responses.activate
    def test_push_repo(self):
        self.mock_create_repo()

        p = self.mk_project(repo={'base_url': self.base_repo_sm.repo.git_dir})

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')

        self.assertFalse(os.path.exists(os.path.join(
            self.base_repo_sm.repo.working_dir, 'text.txt')))

        pw.take_action('push_repo')
        self.assertEquals(p.state, 'repo_pushed')

        self.assertTrue(os.path.exists(os.path.join(
            self.source_repo_sm.repo.working_dir, 'text.txt')))

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @responses.activate
    def test_init_workspace(self):
        self.mock_create_repo()
        self.mock_create_webhook()
        self.mock_create_unicore_distribute_repo()

        p = self.mk_project(repo={'base_url': self.base_repo_sm.repo.git_dir})

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')
        pw.take_action('push_repo')
        pw.take_action('create_webhook')

        self.assertEqual(len(responses.calls), 2)
        self.assertIn('Authorization', responses.calls[-1].request.headers)

        pw.take_action('init_workspace')

        self.assertEquals(p.state, 'workspace_initialized')

        workspace = self.mk_workspace(
            working_dir=settings.CMS_REPO_PATH,
            name='ffl-za',
            index_prefix='unicore_cms_ffl_za')

        self.assertEqual(workspace.S(Category).count(), 1)
        self.assertEqual(workspace.S(Page).count(), 1)
        self.assertEqual(workspace.S(EGLocalisation).count(), 1)

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

        loc = EGLocalisation({
            'locale': 'spa_ES',
            'image': 'some-image-uuid',
            'image_host': 'http://some.site.com',
        })
        workspace.save(loc, 'Saving a Localisation')

        workspace.refresh_index()

        self.assertEqual(workspace.S(Category).count(), 2)
        self.assertEqual(workspace.S(Page).count(), 2)
        self.assertEqual(workspace.S(EGLocalisation).count(), 2)

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @responses.activate
    def test_create_nginx_config(self):
        self.mock_create_repo()
        self.mock_create_webhook()
        self.mock_create_unicore_distribute_repo()

        p = self.mk_project(repo={'base_url': self.base_repo_sm.repo.git_dir})

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')
        pw.take_action('push_repo')
        pw.take_action('create_webhook')
        pw.take_action('init_workspace')
        pw.take_action('create_nginx')

        cms_nginx_config_path = os.path.join(
            settings.NGINX_CONFIGS_PATH,
            'cms_ffl_za.conf')

        self.assertTrue(os.path.exists(cms_nginx_config_path))

        with open(cms_nginx_config_path, "r") as config_file:
            data = config_file.read()

        self.assertTrue('ffl-za-%s.qa-content.unicore.io' % p.id in data)
        self.assertTrue('unicore_cms_django_ffl_za-access.log' in data)
        self.assertTrue('unicore_cms_django_ffl_za-error.log' in data)

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @responses.activate
    def test_create_pyramid_settings(self):
        self.mock_create_repo()
        self.mock_create_webhook()
        self.mock_create_hub_app()
        self.mock_create_unicore_distribute_repo()

        p = self.mk_project(
            repo={'base_url': self.base_repo_sm.repo.git_dir},
            project={'ga_profile_id': 'UA-some-profile-id'})
        p.available_languages.add(Localisation._for('eng_UK'))

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')
        pw.take_action('push_repo')
        pw.take_action('create_webhook')
        pw.take_action('init_workspace')
        pw.take_action('create_nginx')
        pw.take_action('create_hub_app')
        pw.take_action('create_pyramid_settings')

        frontend_settings_path = os.path.join(
            settings.FRONTEND_SETTINGS_OUTPUT_PATH,
            'ffl_za.ini')

        self.assertTrue(os.path.exists(frontend_settings_path))

        with open(frontend_settings_path, "r") as config_file:
            data = config_file.read()

        self.assertTrue('egg:unicore-cms-ffl' in data)
        self.assertTrue(
            "[(u'eng_UK', u'English')]" in data)
        self.assertTrue(
            'git.path = http://servicehost:6543/repos/'
            'unicore-cms-content-ffl-za.json' in data)
        self.assertTrue('pyramid.default_locale_name = eng_GB' in data)
        self.assertTrue('ga.profile_id = UA-some-profile-id' in data)

        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

    @responses.activate
    def test_create_springboard_settings(self):
        self.mock_create_repo()
        self.mock_create_webhook()
        self.mock_create_hub_app()
        self.mock_create_unicore_distribute_repo()

        p = self.mk_project(
            repo={'base_url': self.base_repo_sm.repo.git_dir},
            project={'ga_profile_id': 'UA-some-profile-id'},
            app_type={'project_type': 'springboard'})
        p.available_languages.add(Localisation._for('eng_GB'))
        other_repo = self.mk_project(
            project={'country': 'UK'},
            app_type={'name': 'gem'}).own_repo()
        p.external_repos.add(other_repo)
        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')
        pw.take_action('push_repo')
        pw.take_action('create_webhook')
        pw.take_action('init_workspace')
        pw.take_action('create_nginx')
        pw.take_action('create_hub_app')
        pw.take_action('create_pyramid_settings')

        springboard_settings_path = os.path.join(
            settings.SPRINGBOARD_SETTINGS_OUTPUT_PATH,
            'ffl_za.ini')

        self.assertTrue(os.path.exists(springboard_settings_path))
        with open(springboard_settings_path, "r") as config_file:
            data = config_file.read()

        self.assertTrue('egg:springboard_ffl' in data)
        self.assertTrue('eng_GB' in data)
        self.assertTrue(
            'unicore.content_repo_urls =\n'
            '    http://servicehost:6543/repos/unicore-cms-content-ffl-za.json'
            '\n'
            '    http://servicehost:6543/repos/unicore-cms-content-gem-uk.json'
            in data)
        self.assertTrue('pyramid.default_locale_name = eng_GB' in data)
        self.assertTrue('ga.profile_id = UA-some-profile-id' in data)

    def test_ordering(self):
        p1 = self.mk_project(repo={'base_url': self.base_repo_sm.repo.git_dir})
        p2 = self.mk_project(
            repo={'base_url': self.base_repo_sm.repo.git_dir},
            project={'country': 'KE'},
            app_type={'name': 'gem', 'title': 'Girl Effect Mobile',
                      'project_type': 'unicore-cms'})
        p3 = self.mk_project(
            repo={'base_url': self.base_repo_sm.repo.git_dir},
            project={'country': 'KE'})

        self.assertEquals(Project.objects.all()[0], p3)
        self.assertEquals(Project.objects.all()[1], p1)
        self.assertEquals(Project.objects.all()[2], p2)

        self.assertEquals(
            str(Project.objects.all()[0].application_type),
            'Facts for Life (unicore-cms)')

    def get_mock_app_client(self):
        mock_app_client = mock.Mock()
        mock_app_client.get_app = mock.Mock()
        mock_app_client.get_app.return_value = mock.Mock()
        mock_app_client.create_app = mock.Mock()
        mock_app_client.create_app.return_value = mock.Mock()
        return mock_app_client

    @mock.patch('unicoremc.models.get_hub_app_client')
    def test_hub_app(self, mock_get_client):
        proj = self.mk_project(
            repo={'base_url': self.base_repo_sm.repo.git_dir},
            app_type={'name': 'gem', 'title': 'Girl Effect Mobile',
                      'project_type': 'unicore-cms'})
        self.assertEqual(proj.hub_app(), None)

        app_client = self.get_mock_app_client()
        mock_get_client.return_value = app_client

        proj.hub_app_id = 'abcd'
        app = proj.hub_app()
        self.assertTrue(app)
        app_client.get_app.assert_called_with(proj.hub_app_id)
        # check that the object isn't fetched again on subsequent calls
        self.assertEqual(app, proj.hub_app())
        self.assertEqual(app_client.get_app.call_count, 1)

    @responses.activate
    def test_create_or_update_hub_app(self):
        ffl = AppType._for(
            'ffl', 'Facts for Life', 'unicore-cms',
            'universalcore/unicore-cms-ffl')
        proj = self.mk_project(
            repo={'base_url': self.base_repo_sm.repo.git_dir},
            app_type={'name': 'gem', 'title': 'Girl Effect Mobile',
                      'project_type': 'unicore-cms'})
        self.mock_create_hub_app(uuid='foouuid')

        app = proj.create_or_update_hub_app()
        self.assertEqual(proj.hub_app_id, 'foouuid')
        self.assertEqual(proj.hub_app(), app)
        self.assertIn(
            '"title": "%s"' % proj.hub_app_title(),
            responses.calls[0].request.body)
        self.assertIn(
            '"url": "%s"' % proj.frontend_url(),
            responses.calls[0].request.body)

        responses.reset()
        responses.add(
            responses.GET, re.compile(r'.*/apps/foouuid'),
            body=json.dumps(app.data),
            status=200,
            content_type='application/json')
        responses.add(
            responses.PUT, re.compile(r'.*/apps/foouuid'),
            body='{}', status=200, content_type='application/json')

        proj.application_type = ffl
        app = proj.create_or_update_hub_app()
        self.assertIn(proj.application_type.title, app.get('title'))
        self.assertIn('ffl', app.get('url'))

    @responses.activate
    def test_create_marathon_app_bad_response(self):

        def call_mock(*call_args, **call_kwargs):
            pass

        self.mock_create_repo()
        self.mock_create_webhook()
        self.mock_create_hub_app()
        self.mock_create_unicore_distribute_repo()
        self.mock_create_marathon_app(404)

        p = self.mk_project(
            repo={'base_url': self.base_repo_sm.repo.git_dir},
            project={'ga_profile_id': 'UA-some-profile-id'},
            app_type={'project_type': 'springboard'})
        p.available_languages.add(Localisation._for('eng_GB'))
        self.addCleanup(lambda: shutil.rmtree(p.repo_path()))

        pw = p.get_website_manager().workflow
        pw.take_action('create_repo')
        pw.take_action('clone_repo')
        pw.take_action('create_remote')
        pw.take_action('merge_remote')
        pw.take_action('push_repo')
        pw.take_action('create_webhook')
        pw.take_action('init_workspace')
        pw.take_action('create_nginx')
        pw.take_action('create_hub_app')
        pw.take_action('create_pyramid_settings')
        pw.take_action('create_cms_settings')

        p.db_manager.call_subprocess = call_mock
        pw.take_action('create_db')

        p.db_manager.call_subprocess = call_mock
        pw.take_action('init_db')

        with self.assertRaises(exceptions.MarathonApiException):
            pw.take_action('create_marathon_app')
