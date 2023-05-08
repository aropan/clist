# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from googleapiclient.http import BatchHttpRequest
from legacy.api.google_calendar.common import service
from pytz import UTC
from traceback_with_variables import prints_exc

from clist.models import Contest, Resource

batch = BatchHttpRequest()


def get_all_calendars():
    ret = []
    page_token = None
    while True:
        calendar_list = service.calendarList().list(pageToken=page_token).execute()
        ret += calendar_list["items"]
        page_token = calendar_list.get('nextPageToken')
        if not page_token:
            break
    return ret


def get_all_events(**kwargs):
    ret = []
    page_token = None
    while True:
        events = service.events().list(pageToken=page_token, **kwargs).execute()
        ret += events["items"]
        page_token = events.get('nextPageToken')
        if not page_token:
            break
    return ret


def create_resource_calendar(resource, calendarId=None):
    body = {
        "summary": resource.host,
        "location": resource.url,
        "selected": True,
    }
    if calendarId:
        entry = service.calendars().update(calendarId=calendarId, body=body).execute()
        if entry["id"] != resource.uid:
            raise Exception("Different id calendar for %s, excepted '%s', found '%s'" % (resource,
                                                                                         resource.uid,
                                                                                         entry["id"]))
    else:
        entry = service.calendars().insert(body=body).execute()
        resource.uid = entry["id"]
        resource.save()


def create_contest_event(calendarId, contest, eventId=None):
    body = {
        "summary": contest.title,
        "start": {"dateTime": contest.start_time.isoformat()},
        "end": {"dateTime": contest.end_time.isoformat()},
        "description": "Link: %s\nUpdated: %s\n" % (contest.url, contest.modified.strftime("%Y-%m-%dT%H:%M:%S.%fZ")),
        "visibility": "public",
        "status": "confirmed",
        "transparency": "transparent",
        "attendees": [{"email": "clist.x10.mx@gmail.com", "responseStatus": "accepted"}],
    }
    if eventId:
        entry = service.events().update(calendarId=calendarId, eventId=eventId, body=body).execute()
        if entry["id"] != contest.uid:
            raise Exception("Different id event for %s, excepted '%s', found '%s'" % (contest,
                                                                                      contest.uid,
                                                                                      entry["id"]))
    else:
        entry = service.events().insert(calendarId=calendarId, body=body).execute()
        contest.uid = entry["id"]
        contest.save()
    return entry


def get_time_with_tz(time, tz=UTC):
    return timezone.make_aware(datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%fZ"), tz)


class Command(BaseCommand):
    help = 'Update google calendars'

    @prints_exc
    def handle(self, *args, **options):
        now = timezone.now()
        print(now)
        print()
        current = now - timedelta(days=8)

        calendars = {entry["id"]: entry for entry in get_all_calendars()}

        print(f"Calendars ({len(calendars)}):")
        for c in sorted(list(calendars.values()), key=lambda c: c['summary']):
            print("    %(summary)s, %(id)s" % c)

        resources_uids = set()
        for r in Resource.objects.all():
            if r.uid:
                if r.uid not in calendars:
                    raise Exception("Calendar with id='%s' not found, resource %s" % (r.uid, r.host))
                if calendars[r.uid]["summary"] != r.host:
                    print("!   %s" % r)
                    create_resource_calendar(r, r.uid)
            else:
                print("+   %s" % r)
                create_resource_calendar(r)
            resources_uids.add(r.uid)

        for uid, cal in calendars.items():
            if cal['summary'] == 'CLIST':
                continue
            if uid not in resources_uids:
                print(f"-   {cal['summary']}")
                service.calendarList().delete(calendarId=uid).execute()

        for r in Resource.objects.all():
            events = {entry["id"]: entry for entry in get_all_events(calendarId=r.uid, timeMin=current.isoformat())}
            contests = Contest.visible.filter(resource=r, end_time__gt=current)

            print("%s <%d event(s), %d contest(s)>:" % (r, len(events), len(contests)))
            for c in contests:
                if not c.uid or c.uid not in events:
                    create_contest_event(r.uid, c)
                    print("+   %s" % c)
                elif get_time_with_tz(events[c.uid]["updated"]) < c.modified - timedelta(minutes=1):
                    entry = create_contest_event(r.uid, c, c.uid)
                    updated = get_time_with_tz(entry["updated"])
                    if c.modified - updated > timedelta(minutes=1):
                        print("!   %s" % c)

            for e in list(events.values()):
                if not Contest.visible.filter(resource=r, uid=e["id"]):
                    print("-   %s" % e["summary"])
                    service.events().delete(calendarId=r.uid, eventId=e["id"]).execute()
