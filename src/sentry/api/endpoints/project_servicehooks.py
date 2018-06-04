from __future__ import absolute_import

from django.db import transaction
from rest_framework import status

from sentry import features
from sentry.api.base import DocSection
from sentry.api.bases.project import ProjectEndpoint
from sentry.api.serializers import serialize
from sentry.api.validators import ServiceHookValidator
from sentry.models import AuditLogEntryEvent, ObjectStatus, ServiceHook
from sentry.utils.apidocs import scenario, attach_scenarios


@scenario('ListServiceHooks')
def list_hooks_scenario(runner):
    runner.request(
        method='GET', path='/projects/%s/%s/hooks/' % (runner.org.slug, runner.default_project.slug)
    )


@scenario('CreateServiceHook')
def create_hook_scenario(runner):
    runner.request(
        method='POST',
        path='/projects/%s/%s/hooks/' % (runner.org.slug, runner.default_project.slug),
        data={'url': 'https://example.com/sentry-hook', 'events': ['event.alert', 'event.created']}
    )


class ProjectServiceHooksEndpoint(ProjectEndpoint):
    doc_section = DocSection.PROJECTS

    def has_feature(self, request, project):
        return features.has(
            'projects:servicehooks',
            project=project,
            actor=request.user,
        )

    @attach_scenarios([list_hooks_scenario])
    def get(self, request, project):
        """
        List a Project's Service Hooks
        ``````````````````````````````

        Return a list of service hooks bound to a project.

        :pparam string organization_slug: the slug of the organization the
                                          client keys belong to.
        :pparam string project_slug: the slug of the project the client keys
                                     belong to.
        """
        queryset = ServiceHook.objects.filter(
            project_id=project.id,
        )
        status = request.GET.get('status')
        if status == 'active':
            queryset = queryset.filter(
                status=ObjectStatus.ACTIVE,
            )
        elif status == 'disabled':
            queryset = queryset.filter(
                status=ObjectStatus.DISABLED,
            )
        elif status:
            queryset = queryset.none()

        return self.paginate(
            request=request,
            queryset=queryset,
            order_by='-id',
            on_results=lambda x: serialize(x, request.user),
        )

    @attach_scenarios([create_hook_scenario])
    def post(self, request, project):
        """
        Register a new Service Hook
        ```````````````````````````

        Register a new service hook on a project.

        Events include:

        - event.alert: An alert is generated for an event (via rules).
        - event.created: A new event has been processed.

        :pparam string organization_slug: the slug of the organization the
                                          client keys belong to.
        :pparam string project_slug: the slug of the project the client keys
                                     belong to.
        :param string url: the url for the webhook
        :param array[string] events: the events to subscribe to
        """
        if not request.user.is_authenticated():
            return self.respond(status=401)

        validator = ServiceHookValidator(data=request.DATA)
        if not validator.is_valid():
            return self.respond(validator.errors, status=status.HTTP_400_BAD_REQUEST)

        result = validator.object

        with transaction.atomic():
            hook = ServiceHook.objects.create(
                project_id=project.id,
                url=result['url'],
                actor_id=request.user.id,
                events=result.get('events'),
                application=getattr(request.auth, 'application', None) if request.auth else None,
            )

            self.create_audit_entry(
                request=request,
                organization=project.organization,
                target_object=hook.id,
                event=AuditLogEntryEvent.SERVICEHOOK_ADD,
                data=hook.get_audit_log_data(),
            )

        return self.respond(serialize(hook, request.user), status=201)
