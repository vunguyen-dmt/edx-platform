"""
Utils for discussion API.
"""
from datetime import datetime
from pytz import UTC
from typing import List, Dict

from django.conf import settings
from django.contrib.auth.models import User  # lint-amnesty, pylint: disable=imported-auth-user
from django.core.paginator import Paginator
from django.db.models.functions import Length
from django.utils.translation import gettext_lazy as _

from common.djangoapps.student.models import CourseEnrollment, get_user_by_username_or_email, UserProfile
from common.djangoapps.student.roles import CourseStaffRole, CourseInstructorRole
from lms.djangoapps.discussion.django_comment_client.permissions import get_team
from lms.djangoapps.discussion.django_comment_client.utils import has_discussion_privileges
from openedx.core.djangoapps.course_groups.models import CourseCohortsSettings, CourseUserGroup
from openedx.core.djangoapps.discussions.models import DiscussionsConfiguration, PostingRestriction
from openedx.core.djangoapps.discussions.utils import get_divided_discussions
from openedx.core.djangoapps.django_comment_common.models import (
    Role,
    CourseDiscussionSettings,
    FORUM_ROLE_ADMINISTRATOR,
    FORUM_ROLE_MODERATOR,
    FORUM_ROLE_GROUP_MODERATOR,
    FORUM_ROLE_COMMUNITY_TA,
)
from openedx_events.learning.signals import USER_NOTIFICATION_REQUESTED
from openedx_events.learning.data import UserNotificationData
from openedx.core.djangoapps.django_comment_common.comment_client.comment import Comment


class AttributeDict(dict):
    """
    Converts Dict Keys into Attributes
    """
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def discussion_open_for_user(course, user):
    """
    Check if the course discussion are open or not for user.

    Arguments:
            course: Course to check discussions for
            user: User to check for privileges in course
    """
    discussions_posting_restrictions = DiscussionsConfiguration.get(course.id).posting_restrictions
    blackout_dates = course.get_discussion_blackout_datetimes()
    return (
        is_posting_allowed(discussions_posting_restrictions, blackout_dates) or
        has_discussion_privileges(user, course.id)
    )


def set_attribute(threads, attribute, value):
    """
    Iterates over the list of dicts and assigns the provided value to the given attribute

    Arguments:
        threads: List of threads (dict objects)
        attribute: the key for thread dict
        value: the value to assign to the thread attribute
    """
    for thread in threads:
        thread[attribute] = value
    return threads


def get_usernames_from_search_string(course_id, search_string, page_number, page_size):
    """
    Gets usernames for all users in course that match string.

    Args:
            course_id (CourseKey): Course to check discussions for
            search_string (str): String to search matching
            page_number (int): Page number to fetch
            page_size (int): Number of items in each page

    Returns:
            page_matched_users (str): comma seperated usernames for the page
            matched_users_count (int): count of matched users in course
            matched_users_pages (int): pages of matched users in course
    """
    matched_users_in_course = User.objects.filter(
        courseenrollment__course_id=course_id,
        username__icontains=search_string).order_by(Length('username').asc()).values_list('username', flat=True)
    if not matched_users_in_course:
        return '', 0, 0
    matched_users_count = len(matched_users_in_course)
    paginator = Paginator(matched_users_in_course, page_size)
    page_matched_users = paginator.page(page_number)
    matched_users_pages = int(matched_users_count / page_size)
    return ','.join(page_matched_users), matched_users_count, matched_users_pages


def get_usernames_for_course(course_id, page_number, page_size):
    """
    Gets usernames for all users in course.

    Args:
            course_id (CourseKey): Course to check discussions for
            page_number (int): Page numbers to fetch
            page_size (int): Number of items in each page

    Returns:
            page_matched_users (str): comma seperated usernames for the page
            matched_users_count (int): count of matched users in course
            matched_users_pages (int): pages of matched users in course
    """
    matched_users_in_course = User.objects.filter(courseenrollment__course_id=course_id, ) \
        .order_by(Length('username').asc()).values_list('username', flat=True)
    if not matched_users_in_course:
        return '', 0, 0
    matched_users_count = len(matched_users_in_course)
    paginator = Paginator(matched_users_in_course, page_size)
    page_matched_users = paginator.page(page_number)
    matched_users_pages = int(matched_users_count / page_size)
    return ','.join(page_matched_users), matched_users_count, matched_users_pages


def add_stats_for_users_with_no_discussion_content(course_stats, users_in_course):
    """
    Update users stats for users with no discussion stats available in course
    """
    users_returned_from_api = [user['username'] for user in course_stats]
    user_list = users_in_course.split(',')
    users_with_no_discussion_content = set(user_list) ^ set(users_returned_from_api)
    updated_course_stats = course_stats
    for user in users_with_no_discussion_content:
        updated_course_stats.append({
            'username': user,
            'threads': 0,
            'replies': 0,
            'responses': 0,
            'active_flags': 0,
            'inactive_flags': 0,
        })
    updated_course_stats = sorted(updated_course_stats, key=lambda d: len(d['username']))
    return updated_course_stats


def add_stats_for_users_with_null_values(course_stats, users_in_course):
    """
    Update users stats for users with no discussion stats available in course
    """
    users_returned_from_api = [user['username'] for user in course_stats]
    user_list = users_in_course.split(',')
    users_with_no_discussion_content = set(user_list) ^ set(users_returned_from_api)
    updated_course_stats = course_stats
    for user in users_with_no_discussion_content:
        profile = get_user_profile_by_username(user)
        updated_course_stats.append({
            'username': user,
            'name': profile.name,
            'threads': None,
            'replies': None,
            'responses': None,
            'active_flags': None,
            'inactive_flags': None,
        })
    updated_course_stats = sorted(updated_course_stats, key=lambda d: len(d['username']))
    return updated_course_stats


def get_course_staff_users_list(course_id):
    """
    Gets user ids for Staff roles for course discussions.
    Roles Course Instructor and Course Staff.
    """
    # TODO: cache course_staff_user_ids if we need to improve perf
    course_staff_user_ids = []
    staff = list(CourseStaffRole(course_id).users_with_role().values_list('id', flat=True))
    admins = list(CourseInstructorRole(course_id).users_with_role().values_list('id', flat=True))
    course_staff_user_ids.extend(staff)
    course_staff_user_ids.extend(admins)
    return list(set(course_staff_user_ids))


def get_course_ta_users_list(course_id):
    """
    Gets user ids for TA roles for course discussions.
    Roles include Community TA and Group Community TA.
    """
    # TODO: cache ta_users_ids if we need to improve perf
    ta_users_ids = [
        user.id
        for role in Role.objects.filter(name__in=[FORUM_ROLE_GROUP_MODERATOR,
                                                  FORUM_ROLE_COMMUNITY_TA], course_id=course_id)
        for user in role.users.all()
    ]
    return ta_users_ids


def get_moderator_users_list(course_id):
    """
    Gets user ids for Moderator roles for course discussions.
    Roles include Discussion Administrator and Discussion Moderator.
    """
    # TODO: cache moderator_user_ids if we need to improve perf
    moderator_user_ids = [
        user.id
        for role in Role.objects.filter(
            name__in=[FORUM_ROLE_ADMINISTRATOR, FORUM_ROLE_MODERATOR],
            course_id=course_id
        )
        for user in role.users.all()
    ]
    return moderator_user_ids


def add_name_for_users_stats(users_stats):
    update_profile_name_in_course_stats = list()
    for user in users_stats:
        profile = get_user_profile_by_username(user['username'])
        update_profile_name_in_course_stats.append({
            'username': user['username'],
            'name': profile.name,
            'threads': user['threads'],
            'replies': user['replies'],
            'responses': user['responses'],
            'active_flags': user['active_flags'],
            'inactive_flags': user['inactive_flags'],
        })
    return update_profile_name_in_course_stats


def get_user_profile_by_username(user_name):
    matched_user = get_user_by_username_or_email(user_name)
    user_profile = UserProfile.objects.get(user=matched_user)
    return user_profile


def filter_topic_from_discussion_id(discussion_id, topics_list):
    """
    Returns topic based on discussion id
    """
    for topic in topics_list:
        if topic.get("id") == discussion_id:
            return topic
    return {}


def create_discussion_children_from_ids(children_ids, blocks, topics):
    """
    Takes ids of discussion and return discussion dictionary
    """
    discussions = []
    for child_id in children_ids:
        topic = blocks.get(child_id)
        if topic.get('type') == 'vertical':
            discussions_id = topic.get('discussions_id')
            topic = filter_topic_from_discussion_id(discussions_id, topics)
        if topic:
            discussions.append(topic)
    return discussions


def create_blocks_params(course_usage_key, user):
    """
    Returns param dict that is needed to get blocks
    """
    return {
        'usage_key': course_usage_key,
        'user': user,
        'depth': None,
        'nav_depth': None,
        'requested_fields': {
            'display_name',
            'student_view_data',
            'children',
            'discussions_id',
            'type',
            'block_types_filter'
        },
        'block_counts': set(),
        'student_view_data': {'discussion'},
        'return_type': 'dict',
        'block_types_filter': {
            'discussion',
            'chapter',
            'vertical',
            'sequential',
            'course'
        }
    }


def add_thread_stats_to_subsection(topics_list):
    """
    Add topic stats at subsection by adding stats of all units in
    the topic
    """
    for section in topics_list:
        for subsection in section.get('children', []):
            discussions = 0
            questions = 0
            for unit in subsection.get('children', []):
                thread_counts = unit.get('thread_counts', {})
                discussions += thread_counts.get('discussion', 0)
                questions += thread_counts.get('question', 0)
            subsection['thread_counts'] = {
                'discussion': discussions,
                'question': questions,
            }


def create_topics_v3_structure(blocks, topics):
    """
    Create V3 topics structure from blocks and v2 topics
    """
    non_courseware_topics = [
        dict({**topic, 'courseware': False})
        for topic in topics
        if topic.get('usage_key', '') is None
    ]
    courseware_topics = []
    for key, value in blocks.items():
        if value.get("type") == "chapter":
            value['courseware'] = True
            courseware_topics.append(value)
            value['children'] = create_discussion_children_from_ids(
                value.get('children', []),
                blocks,
                topics,
            )
            subsections = value.get('children')
            for subsection in subsections:
                subsection['children'] = create_discussion_children_from_ids(
                    subsection.get('children', []),
                    blocks,
                    topics,
                )

    add_thread_stats_to_subsection(courseware_topics)
    structured_topics = non_courseware_topics + courseware_topics
    topic_ids = get_topic_ids_from_topics(topics)

    # Remove all topic ids that are contained in the structured topics
    for chapter in structured_topics:
        for sequential in chapter.get('children', []):
            for item in sequential['children']:
                topic_ids.remove(item['id'])

    archived_topics = {
        'id': "archived",
        'children': get_archived_topics(topic_ids, topics)
    }
    if archived_topics['children']:
        structured_topics.append(archived_topics)

    return remove_empty_sequentials(structured_topics)


def remove_empty_sequentials(data):
    """
    Removes all objects of type "sequential" from a nested list of objects if they
    have no children.
    After removing the empty sequentials, if the parent of the sequential is now empty,
    it will also be removed.
    Parameters:
    data (list): A list of nested objects to check and remove empty sequentials from.

    Returns:
    list: The modified list with empty sequentials removed.
    """
    new_data = []
    for obj in data:
        block_type = obj.get('type')
        if block_type != 'sequential' or (block_type == 'sequential' and obj.get('children')):
            if obj.get('children'):
                obj['children'] = remove_empty_sequentials(obj['children'])
                if obj['children'] or block_type != 'chapter':
                    new_data.append(obj)
            else:
                if block_type != 'chapter':
                    new_data.append(obj)
    return new_data


def get_topic_ids_from_topics(topics: List[Dict[str, str]]) -> List[str]:
    """
    This function takes a list of topics and returns a list of the topic ids.

    Args:
    - topics (List[Dict[str, str]]): A list of topic dictionaries. Each dictionary should have an 'id' field.

    Returns:
    - A list of topic ids, extracted from the input list of topics.
    """
    return [topic['id'] for topic in topics]


def get_archived_topics(filtered_topic_ids: List[str], topics: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    This function takes a list of topic ids and a list of topics, and returns the list of archived topics.

    A topic is considered archived if it has a non-null `usage_key` field.

    Args:
    - filtered_topic_ids (List[str]): A list of topic ids to filter on.
    - topics (List[Dict[str, str]]): A list of topic dictionaries.
    - Each dictionary should have a 'id' and a 'usage_key' field.

    Returns:
    - A list of archived topic dictionaries, with the same format as the input topics.
    """
    archived_topics = []
    for topic_id in filtered_topic_ids:
        for topic in topics:
            if topic['id'] == topic_id and topic['usage_key'] is not None:
                archived_topics.append(topic)
    return archived_topics


def is_discussion_cohorted(course_key_str):
    """
    Returns if the discussion is divided by cohorts
    """
    cohort_settings = CourseCohortsSettings.objects.get(course_id=course_key_str)
    discussion_settings = CourseDiscussionSettings.objects.get(course_id=course_key_str)
    return cohort_settings.is_cohorted and discussion_settings.always_divide_inline_discussions


class DiscussionNotificationSender:
    """
    Class to send notifications to users who are subscribed to the thread.
    """

    def __init__(self, thread, course, creator, parent_id=None):
        self.thread = thread
        self.course = course
        self.creator = creator
        self.parent_id = parent_id
        self.parent_response = None
        self._get_parent_response()

    def _send_notification(self, user_ids, notification_type, extra_context=None):
        """
        Send notification to users
        """
        if not user_ids:
            return

        if extra_context is None:
            extra_context = {}

        notification_data = UserNotificationData(
            user_ids=[int(user_id) for user_id in user_ids],
            context={
                "replier_name": self.creator.username,
                "post_title": self.thread.title,
                "course_name": self.course.display_name,
                **extra_context,
            },
            notification_type=notification_type,
            content_url=f"{settings.DISCUSSIONS_MICROFRONTEND_URL}/{str(self.course.id)}/posts/{self.thread.id}",
            app_name="discussion",
            course_key=self.course.id,
        )
        USER_NOTIFICATION_REQUESTED.send_event(notification_data=notification_data)

    def _get_parent_response(self):
        """
        Get parent response object
        """
        if self.parent_id and not self.parent_response:
            self.parent_response = Comment(id=self.parent_id).retrieve()

        return self.parent_response

    def _create_cohort_course_audience(self):
        """
        Creates audience based on user cohort and role
        """
        course_key_str = str(self.course.id)
        discussion_cohorted = is_discussion_cohorted(course_key_str)

        # Retrieves cohort divided discussion
        discussion_settings = CourseDiscussionSettings.objects.get(course_id=course_key_str)
        divided_course_wide_discussions, divided_inline_discussions = get_divided_discussions(
            self.course,
            discussion_settings
        )

        # Checks if post has any cohort assigned
        group_id = self.thread.attributes['group_id']
        if group_id is not None:
            group_id = int(group_id)

        # Course wide topics
        topic_id = self.thread.attributes['commentable_id']
        all_topics = divided_inline_discussions + divided_course_wide_discussions
        topic_divided = topic_id in all_topics or discussion_settings.always_divide_inline_discussions

        # Team object from topic id
        team = get_team(topic_id)

        user_ids = []
        if team:
            user_ids = team.users.all().values_list('id', flat=True)
        elif discussion_cohorted and topic_divided and group_id is not None:
            users_in_cohort = CourseUserGroup.objects.filter(
                course_id=course_key_str, id=group_id
            ).values_list('users__id', flat=True)
            user_ids.extend(users_in_cohort)

            privileged_roles = [FORUM_ROLE_ADMINISTRATOR, FORUM_ROLE_MODERATOR, FORUM_ROLE_COMMUNITY_TA]
            privileged_users = Role.objects.filter(
                name__in=privileged_roles,
                course_id=course_key_str
            ).values_list('users__id', flat=True)
            user_ids.extend(privileged_users)

            staff_users = CourseStaffRole(self.course.id).users_with_role().values_list('id', flat=True)
            user_ids.extend(staff_users)

            admin_users = CourseInstructorRole(self.course.id).users_with_role().values_list('id', flat=True)
            user_ids.extend(admin_users)
        else:
            user_ids = CourseEnrollment.objects.filter(
                course__id=course_key_str, is_active=True
            ).values_list('user__id', flat=True)

        unique_user_ids = list(set(user_ids))
        if self.creator.id in unique_user_ids:
            unique_user_ids.remove(self.creator.id)
        return unique_user_ids

    def send_new_response_notification(self):
        """
        Send notification to users who are subscribed to the main thread/post i.e.
        there is a response to the main thread.
        """
        if not self.parent_id and self.creator.id != int(self.thread.user_id):
            self._send_notification([self.thread.user_id], "new_response")

    def _response_and_thread_has_same_creator(self) -> bool:
        """
        Check if response and main thread have same author.
        """
        return int(self.parent_response.user_id) == int(self.thread.user_id)

    def _response_and_comment_has_same_creator(self):
        return int(self.parent_response.attributes['user_id']) == self.creator.id

    def send_new_comment_notification(self):
        """
        Send notification to parent thread creator i.e. comment on the response.
        """
        if (
            self.parent_response and
            self.creator.id != int(self.thread.user_id)
        ):
            # use your if author of response is same as author of post.
            # use 'their' if comment author is also response author.
            author_name = (
                # Translators: Replier commented on "your" response to your post
                _("your")
                if self._response_and_thread_has_same_creator()
                else (
                    # Translators: Replier commented on "their" response to your post
                    _("their")
                    if self._response_and_comment_has_same_creator()
                    else f"{self.parent_response.username}'s"
                )
            )
            context = {
                "author_name": str(author_name),
            }
            self._send_notification([self.thread.user_id], "new_comment", extra_context=context)

    def send_new_comment_on_response_notification(self):
        """
        Send notification to parent response creator i.e. comment on the response.
        Do not send notification if author of response is same as author of post.
        """
        if (
            self.parent_response and
            self.creator.id != int(self.parent_response.user_id) and not
            self._response_and_thread_has_same_creator()
        ):
            self._send_notification([self.parent_response.user_id], "new_comment_on_response")

    def send_new_thread_created_notification(self):
        """
        Send notification based on notification_type
        """
        thread_type = self.thread.attributes['thread_type']
        notification_type = (
            "new_question_post"
            if thread_type == "question"
            else ("new_discussion_post" if thread_type == "discussion" else "")
        )
        if notification_type not in ['new_discussion_post', 'new_question_post']:
            raise ValueError(f'Invalid notification type {notification_type}')

        user_ids = self._create_cohort_course_audience()
        context = {
            'username': self.creator.username,
            'post_title': self.thread.title
        }
        self._send_notification(user_ids, notification_type, context)


def is_posting_allowed(posting_restrictions: str, blackout_schedules: List):
    """
    Check if posting is allowed based on the given posting restrictions and blackout schedules.

    Args:
        posting_restrictions (str): Values would be  "disabled", "scheduled" or "enabled".
        blackout_schedules (List[Dict[str, datetime]]): The list of blackout schedules

    Returns:
        bool: True if posting is allowed, False otherwise.
    """
    now = datetime.now(UTC)
    if posting_restrictions == PostingRestriction.DISABLED:
        return True
    elif posting_restrictions == PostingRestriction.SCHEDULED:
        return not any(schedule["start"] <= now <= schedule["end"] for schedule in blackout_schedules)
    else:
        return False
