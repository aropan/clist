from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils.timezone import now
from django_ical.views import ICalFeed

from clist.models import Contest
from notification.models import Calendar


class EventFeed(ICalFeed):

    def __call__(self, request, uuid, *args, **kwargs):
        self.request = request
        self.uuid = uuid
        return super().__call__(request, *args, **kwargs)

    def items(self):
        calendar = get_object_or_404(Calendar.objects.select_related('coder'), uuid=self.uuid)
        contests = Contest.visible.filter(end_time__gt=now() - timedelta(days=31))
        if calendar.category:
            contests = contests.filter(calendar.coder.get_contest_filter(calendar.category))
        if calendar.resources:
            contests = contests.filter(resource_id__in=calendar.resources)
        return contests

    def item_title(self, item):
        return item.title

    def item_guid(self, item):
        return item.pk

    def item_description(self, item):
        return item.host

    def item_link(self, item):
        return item.actual_url

    def item_start_datetime(self, item):
        return item.start_time

    def item_end_datetime(self, item):
        return item.end_time

    def item_updateddate(self, item):
        return item.modified


@login_required
def messages(request):
    coder = request.as_coder or request.user.coder
    update = not bool(request.as_coder)

    messages = coder.messages_set.order_by('-created')
    context = {
        'notification_messages': messages,
    }
    response = render(request, 'notification_messages.html', context)

    if update:
        messages.filter(is_read=False).update(is_read=True, read_at=now())

    return response
