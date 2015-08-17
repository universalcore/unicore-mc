import json

import responses

from django.test import TestCase
from django.contrib.auth import get_user_model

from unicoremc.managers.infrastructure import (
    GeneralInfrastructureManager, InfrastructureError)
from unicoremc.models import Project, AppType


class GeneralInfrastructureManagerTest(TestCase):

    def setUp(self):

        User = get_user_model()
        user = User.objects.create_user(
            'tester', 'test@example.org', 'tester')
        app_type = AppType._for(
            'gem', 'Girl Effect', 'unicore-cms',
            'universalcore/unicore-cms-gem')
        self.project = Project(application_type=app_type,
                               country='ZA', owner=user)
        self.project.save()

        responses.add(
            responses.GET,
            'http://testserver:8080/v2/apps/%s' % (self.project.app_id,),
            status=200, content_type='application/json',
            body=json.dumps({
                "app": {
                    "id": "/%s" % (self.project.app_id,),
                }
            }))

        responses.add(
            responses.GET,
            'http://testserver:8080/v2/apps/%s/tasks' % (self.project.app_id,),
            status=200, content_type='application/json',
            body=json.dumps({
                "tasks": [{
                    "appId": "/%s" % (self.project.app_id,),
                    "id": "%s.the-task-id" % (self.project.app_id,),
                    "host": "worker-machine-1",
                    "ports": [8898],
                    "startedAt": "2015-08-10T16:09:43.561Z",
                    "stagedAt": "2015-08-10T16:09:35.436Z",
                    "version": "2015-07-31T15:41:42.894Z",
                    "healthCheckResults": [],
                }]
            }))

        responses.add(
            responses.GET, 'http://testserver:8080/v2/info',
            status=200, content_type='application/json',
            body=json.dumps({
                "name": "marathon",
                "frameworkId": "the-framework-id",
            }))

        responses.add(
            responses.GET, 'http://worker-machine-1:5555/state.json',
            status=200, content_type='application/json',
            body=json.dumps({
                "id": "worker-machine-id",
            })
        )
        self.general_im = GeneralInfrastructureManager()
        self.project_im = self.project.infra_manager

    @responses.activate
    def test_get_marathon_app(self):
        app = self.general_im.get_marathon_app(self.project.app_id)
        self.assertEqual(app['id'], '/%s' % (self.project.app_id,))

    @responses.activate
    def test_get_marathon_app_tasks(self):
        [task] = self.general_im.get_marathon_app_tasks(self.project.app_id)
        self.assertEqual(task['appId'], '/%s' % (self.project.app_id,))
        self.assertEqual(
            task['id'], '%s.the-task-id' % (self.project.app_id,))
        self.assertEqual(task['ports'], [8898])
        self.assertEqual(task['host'], 'worker-machine-1')

    @responses.activate
    def test_get_marathon_info(self):
        info = self.general_im.get_marathon_info()
        self.assertEqual(info['name'], 'marathon')
        self.assertEqual(info['frameworkId'], 'the-framework-id')

    @responses.activate
    def test_get_worker_info(self):
        worker = self.general_im.get_worker_info('worker-machine-1')
        self.assertEqual(worker['id'], 'worker-machine-id')

    @responses.activate
    def test_get_app_log_urls(self):
        urls = list(self.general_im.get_app_log_urls(self.project.app_id))
        self.assertEqual(
            urls,
            [('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stdout') % (
                self.project.app_id,),
             ('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stderr') % (
                self.project.app_id,),
             ])

    @responses.activate
    def test_get_task_log_urls(self):
        urls = list(self.general_im.get_task_log_urls(
            self.project.app_id,
            '%s.the-task-id' % (self.project.app_id,),
            'worker-machine-1'))
        self.assertEqual(
            urls,
            [('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stdout') % (
                self.project.app_id,),
             ('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stderr') % (
                self.project.app_id,),
             ])

    @responses.activate
    def test_project_infra_manager_get_marathon_app(self):
        app = self.project_im.get_project_marathon_app()
        self.assertEqual(app['id'], '/%s' % (self.project.app_id,))

    @responses.activate
    def test_project_infra_manager_get_project_log_urls(self):
        urls = self.project_im.get_project_log_urls()
        self.assertEqual(
            list(urls),
            [('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stdout') % (
                self.project.app_id,),
             ('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stderr') % (
                self.project.app_id,),
             ])

    @responses.activate
    def test_project_infra_manager_get_project_task_log_urls(self):
        urls = self.project_im.get_project_task_log_urls(
            '%s.the-task-id' % (self.project.app_id,))
        self.assertEqual(
            list(urls),
            [('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stdout') % (
                self.project.app_id,),
             ('http://worker-machine-1:3333/tail'
              '/worker-machine-id/frameworks/the-framework-id'
              '/executors/%s.the-task-id/runs/latest/stderr') % (
                self.project.app_id,),
             ])

    @responses.activate
    def test_project_infra_manager_get_project_non_existent(self):
        self.assertRaises(
            InfrastructureError,
            self.project_im.get_project_task_log_urls, 'non-existing-task-id')
