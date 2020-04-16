import random
import csv
from datetime import timedelta
from urllib.parse import urlparse
from collections import Counter

from django.db import models
from django_enumfield.enum import Enum
from django_enumfield.db.fields import EnumField
from django.template.loader import get_template
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend
from django.contrib.postgres.fields import JSONField
from django.utils.timezone import now
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField

from pyclist.models import BaseModel
from true_coders.models import Coder, Organization


class Event(BaseModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    registration_deadline = models.DateTimeField()
    website_url = models.URLField(null=True, blank=True)
    information = models.CharField(max_length=4096)
    email_conf = JSONField(default=dict, blank=True)
    logins_paths = JSONField(default=dict, blank=True)
    standings_urls = JSONField(default=dict, blank=True)
    limits = JSONField(default=dict, blank=True)
    fields_info = JSONField(default=dict, blank=True)
    team_size = models.IntegerField(default=3)

    def email_backend(self):
        return EmailBackend(**self.email_conf['connection'])

    def __str__(self):
        return "%s" % (self.name)

    def host_website_url(self):
        return urlparse(self.website_url).netloc


class TshirtSize(Enum):
    S = 1
    M = 2
    L = 3
    XL = 4
    XXL = 5
    XXXL = 6

    labels = {
        S: 'S',
        M: 'M',
        L: 'L',
        XL: 'XL',
        XXL: 'XXL',
        XXXL: 'XXXL',
    }


class ParticipantManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset() \
            .select_related('coder', 'event', 'team', 'organization')


class Participant(BaseModel):
    coder = models.ForeignKey(Coder, null=True, blank=True, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    team = models.ForeignKey('Team', related_name='participants', null=True, blank=True, on_delete=models.CASCADE)
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    first_name_native = models.CharField(max_length=255, blank=True)
    last_name_native = models.CharField(max_length=255, blank=True)
    middle_name_native = models.CharField(max_length=255, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone_number = PhoneNumberField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL)
    country = CountryField(null=True, blank=True)
    tshirt_size = EnumField(TshirtSize, null=True, blank=True)
    is_coach = models.BooleanField(default=False)
    addition_fields = JSONField(default=dict, blank=True)

    objects = ParticipantManager()

    def __str__(self):
        return "%s %s" % (self.first_name, self.last_name)

    @property
    def tshirt_size_value(self):
        return TshirtSize.labels[self.tshirt_size] if self.tshirt_size else None


class TeamStatus(Enum):
    PENDING = 0
    EDITING = 1
    CANCELLED = 2
    QUALIFICATION = 3
    QUARTERFINAL = 14
    SEMIFINAL = 4
    FINAL = 5
    DISQUALIFIED = 7
    NEW = 9
    ADD_COACH = 10
    BSU_SEMIFINAL = 11
    INVITED = 12
    SCHOOL_FINAL = 13
    SCHOOL_SEMIFINAL = 15

    labels = {
        PENDING: 'pending',
        EDITING: 'editing',
        CANCELLED: 'cancelled',
        QUALIFICATION: 'qualification',
        QUARTERFINAL: 'quarterfinal',
        SEMIFINAL: 'semifinal',
        SCHOOL_SEMIFINAL: 'junior semifinal',
        FINAL: 'final',
        SCHOOL_FINAL: 'junior final',
        DISQUALIFIED: 'disqualified',
        NEW: 'new',
        ADD_COACH: 'coaching',
        BSU_SEMIFINAL: 'bsu',
        INVITED: 'invited',
    }

    frame_labels = {
        PENDING: 'pending',
        EDITING: 'editing',
        CANCELLED: 'cancelled',
        QUALIFICATION: 'qualification',
        QUARTERFINAL: 'quarterfinal',
        SEMIFINAL: 'semifinal',
        FINAL: 'final',
        DISQUALIFIED: 'disqualified',
        NEW: 'new',
        ADD_COACH: 'coaching',
        BSU_SEMIFINAL: 'semifinal',
        INVITED: 'invited',
        SCHOOL_FINAL: 'junior final',
        SCHOOL_SEMIFINAL: 'junior semifinal',
    }

    descriptions = {
        PENDING: 'pending',
        EDITING: 'pending',
        CANCELLED: 'canceled',
        QUALIFICATION: 'approved',
        QUARTERFINAL: 'approved',
        SEMIFINAL: 'approved',
        FINAL: 'approved',
        DISQUALIFIED: 'disqualified',
        NEW: 'new',
        ADD_COACH: 'new',
        BSU_SEMIFINAL: 'approved',
        INVITED: 'invited',
        SCHOOL_FINAL: 'approved',
        SCHOOL_SEMIFINAL: 'approved',
    }

    classes = {
        PENDING: 'warning',
        EDITING: 'warning',
        CANCELLED: 'danger',
        QUALIFICATION: 'success',
        QUARTERFINAL: 'success',
        SEMIFINAL: 'success',
        FINAL: 'success',
        DISQUALIFIED: 'danger',
        NEW: 'default',
        ADD_COACH: 'default',
        BSU_SEMIFINAL: 'success',
        INVITED: 'default',
        SCHOOL_FINAL: 'success',
        SCHOOL_SEMIFINAL: 'success',
    }


class TeamManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset() \
            .select_related(
                'coach__organization',
                'author__organization',
                'event',
            ) \
            .prefetch_related('participants') \
            .annotate(participants_count=models.Count('participants'))


class Team(BaseModel):
    name = models.CharField(max_length=255)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    author = models.ForeignKey(Participant,
                               related_name='team_author_set',
                               on_delete=models.CASCADE)
    coach = models.ForeignKey(Participant,
                              related_name='team_coach_set',
                              null=True,
                              blank=True,
                              on_delete=models.CASCADE)
    status = EnumField(TeamStatus, default=TeamStatus.NEW)

    objects = TeamManager()

    def __str__(self):
        return self.name

    @property
    def ordered_participants(self):
        ret = []
        for p in self.participants.all():
            if p == self.author:
                ret.insert(0, p)
            else:
                ret.append(p)
        return ret

    @property
    def title(self):
        organizations = '+'.join(sorted(set(
            p.organization.abbreviation or 'none'
            for p in self.participants.all()
            if p.organization
        )))
        names = ', '.join(p.last_name for p in self.ordered_participants)
        ret = f'{self.name}: {names}'
        if organizations:
            ret = f'[{organizations}] {ret}'
        return ret

    @property
    def members(self):
        ret = self.ordered_participants
        if self.coach:
            ret.append(self.coach)
        return ret

    @property
    def organizations(self):
        ret = [p.organization for p in self.participants.all() if p.organization]
        duplicate = set()
        ret = [x for x in ret if x.id not in duplicate and not duplicate.add(x.id)]
        return ret

    @property
    def country(self):
        country, repeat = Counter(p.country.name for p in self.participants.all()).most_common(1)[0]
        return country

    @property
    def status_label(self):
        return TeamStatus.labels[self.status]

    def attach_login(self, cache=None):
        event = self.event
        filename = event.logins_paths[self.status_label]
        if cache is None or filename not in cache:
            passwords = {}
            with open(filename, 'r') as fo:
                reader = csv.reader(fo)
                for username, password in reader:
                    login = Login.objects.filter(username=username).first()
                    if login is None:
                        passwords[username] = password
                    elif login.password != password:
                        login.password = password
                        login.save()
            if cache is not None:
                cache[filename] = passwords
        else:
            passwords = cache[filename]

        if Login.objects.filter(team=self, stage=self.status).exists():
            return False, None

        username = random.choice(list(passwords.keys()))
        password = passwords.pop(username)
        login = Login.objects.create(team=self, stage=self.status, username=username, password=password)
        return True, login

    class Meta:
        unique_together = ('name', 'event', )


class JoinRequestManager(models.Manager):
    DELAY_BEFORE_DELETE = timedelta(hours=1)

    def get_queryset(self):
        qs = super(JoinRequestManager, self).get_queryset()
        qs.filter(created__lte=now() - self.DELAY_BEFORE_DELETE).delete()
        return qs


class JoinRequest(BaseModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)

    def __str__(self):
        return "%s to %s" % (self.participant, self.team)

    def repeat_request_timedelta(self):
        return JoinRequest.objects.DELAY_BEFORE_DELETE - (now() - self.created)

    objects = JoinRequestManager()

    class Meta:
        unique_together = ('team', 'participant', )


class Login(BaseModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    stage = EnumField(TeamStatus)
    username = models.CharField(max_length=256, null=False, unique=True)
    password = models.CharField(max_length=256, null=False)
    is_sent = models.BooleanField(default=False)

    def send_email(self, **kwargs):
        if self.is_sent:
            return
        event = self.team.event
        filepath = event.email_conf['logins-templates'][TeamStatus.labels[self.stage]]
        template = get_template(filepath)
        message = template.render({'login': self, 'team': self.team})
        subject, message = message.split('\n\n', 1)
        message = message.replace('\n', '<br>\n')
        to = []
        for m in self.team.ordered_participants:
            to.append(m.email)
        msg = EmailMultiAlternatives(
            subject,
            message,
            to=to,
            **kwargs
        )
        msg.attach_alternative(message, 'text/html')
        result = msg.send()
        if result:
            self.is_sent = True
            self.save()
        return result

    def __str__(self):
        return '%s in %s' % (self.username, TeamStatus.labels[self.stage])

    class Meta:
        unique_together = (('team', 'stage'), ('stage', 'username'))
