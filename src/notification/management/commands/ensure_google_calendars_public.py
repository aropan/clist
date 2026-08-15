#!/usr/bin/env python3

from logging import getLogger

from django.core.management.base import BaseCommand, CommandError

from clist.models import Resource
from legacy.api.google_calendar.acl import PUBLIC_ROLE, ensure_calendar_public
from legacy.api.google_calendar.common import service
from utils.attrdict import AttrDict

MAIN_CALENDAR_SUMMARY = "CLIST"


def get_all_calendars():
    calendars = []
    page_token = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        calendars.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return calendars


class Command(BaseCommand):
    help = "Ensure managed Google calendars are publicly readable"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger("notification.ensure_google_calendars_public")

    def add_arguments(self, parser):
        parser.add_argument("-r", "--resources", metavar="HOST", nargs="*", help="resource hosts")
        parser.add_argument("--dryrun", action="store_true", help="report private calendars without changing ACLs")

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.objects.exclude(uid__isnull=True).exclude(uid="").only("host", "uid")
        if args.resources:
            resources = Resource.get(args.resources, queryset=resources, raise_exception=CommandError)

        calendars = {calendar["id"]: calendar for calendar in get_all_calendars()}
        managed_calendars = {}
        errors = []

        for resource in resources:
            calendar = calendars.get(resource.uid)
            if calendar is None:
                errors.append(f"{resource.host}: calendar {resource.uid!r} is missing")
                continue
            managed_calendars[resource.uid] = (resource.host, calendar)

        if not args.resources:
            for calendar in calendars.values():
                if calendar.get("summary") == MAIN_CALENDAR_SUMMARY:
                    managed_calendars.setdefault(calendar["id"], (MAIN_CALENDAR_SUMMARY, calendar))

        already_public = 0
        needs_update = 0
        for calendar_id, (calendar_summary, calendar) in sorted(managed_calendars.items(), key=lambda item: item[1][0]):
            if calendar.get("accessRole") != "owner":
                errors.append(f"{calendar_summary}: owner access is required to change the calendar ACL")
                continue

            try:
                previous_role = ensure_calendar_public(service, calendar_id, dryrun=args.dryrun)
            except Exception as error:
                self.logger.exception("Failed to update public access for %s", calendar_summary)
                errors.append(f"{calendar_summary}: {error}")
                continue

            if previous_role == PUBLIC_ROLE:
                already_public += 1
                self.stdout.write(f"=   {calendar_summary}: public reader")
                continue

            needs_update += 1
            previous_access = previous_role or "private"
            calendar_action = "would make public" if args.dryrun else "made public"
            self.stdout.write(f"+   {calendar_summary}: {calendar_action} (was {previous_access})")

        report_action = "would update" if args.dryrun else "updated"
        report = (
            f"Calendars: {len(managed_calendars)}, public: {already_public}, "
            f"{report_action}: {needs_update}, errors: {len(errors)}"
        )
        self.stdout.write(report)
        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError(f"Failed to verify {len(errors)} calendar(s)")
