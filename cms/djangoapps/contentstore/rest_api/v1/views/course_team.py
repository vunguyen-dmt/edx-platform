""" API Views for course team """

import edx_api_doc_tools as apidocs
from opaque_keys.edx.keys import CourseKey
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.djangoapps.contentstore.utils import get_course_team
from common.djangoapps.student.auth import STUDIO_VIEW_USERS, get_user_permissions
from openedx.core.lib.api.view_utils import DeveloperErrorViewMixin, verify_course_exists, view_auth_classes

from ..serializers import CourseTeamSerializer

from common.djangoapps.student.roles import (
    CourseBetaTesterRole,
    CourseInstructorRole,
    CourseLimitedStaffRole,
    CourseStaffRole,
)
from common.djangoapps.student.roles import (
    GlobalStaff
)
from django.contrib.auth.models import User

@view_auth_classes(is_authenticated=True)
class CourseTeamView(DeveloperErrorViewMixin, APIView):
    """
    View for getting data for course team.
    """
    @apidocs.schema(
        parameters=[
            apidocs.string_parameter("course_id", apidocs.ParameterLocation.PATH, description="Course ID"),
        ],
        responses={
            200: CourseTeamSerializer,
            401: "The requester is not authenticated.",
            403: "The requester cannot access the specified course.",
            404: "The requested course does not exist.",
        },
    )
    @verify_course_exists()
    def get(self, request: Request, course_id: str):
        """
        Get all CMS users who are editors for the specified course.

        **Example Request**

            GET /api/contentstore/v1/course_team/{course_id}

        **Response Values**

        If the request is successful, an HTTP 200 "OK" response is returned.

        The HTTP 200 response contains a single dict that contains keys that
        are the course's team info.

        **Example Response**

        ```json
        {
            "show_transfer_ownership_hint": true,
            "users": [
                {
                    "email": "edx@example.com",
                    "id": "3",
                    "role": "instructor",
                    "username": "edx"
                },
            ],
            "allow_actions": true
        }
        ```
        """
        user = request.user
        course_key = CourseKey.from_string(course_id)

        user_perms = get_user_permissions(user, course_key)
        if not user_perms & STUDIO_VIEW_USERS:
            self.permission_denied(request)

        course_team_context = get_course_team(user, course_key, user_perms)
        serializer = CourseTeamSerializer(course_team_context)
        return Response(serializer.data)

    @verify_course_exists()
    def post(self, request: Request, course_id: str):
        """
        set course team member.
        """
        course_key = CourseKey.from_string(course_id)
        user_perms = get_user_permissions(request.user, course_key)
        if not GlobalStaff().has_user(request.user):
            self.permission_denied(request)
        if not user_perms & STUDIO_VIEW_USERS:
            self.permission_denied(request)
        ROLES = {
            'beta': CourseBetaTesterRole,
            'instructor': CourseInstructorRole,
            'staff': CourseStaffRole,
            'limited_staff': CourseLimitedStaffRole
        }
        level = request.query_params.get('level')
        action = request.query_params.get('action')
        email = request.query_params.get('email')
        try:
            role = ROLES[level](course_key)
        except KeyError:
            raise ValueError(f"unrecognized level '{level}'")  # lint-amnesty, pylint: disable=raise-missing-from
        try:
            user = User.objects.get(email=email)
        except Exception:  # pylint: disable=broad-except
            return Response(status=404)
        if action == 'allow':
            role.add_users(user)
        elif action == 'revoke':
            role.remove_users(user)
        else:
            raise ValueError(f"unrecognized action '{action}'")
        return Response(status=200)
