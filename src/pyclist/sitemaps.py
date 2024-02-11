from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse
from sql_util.utils import SubqueryMax

from clist.models import Contest, Resource
from clist.templatetags.extras import slug
from ranking.models import Statistics


class BaseSitemap(Sitemap):
    protocol = 'https'
    abstract = True


class StaticViewSitemap(BaseSitemap):
    priority = 1
    changefreq = 'daily'

    def items(self):
        return ['clist:main', 'clist:resources', 'ranking:standings_list', 'clist:problems', 'coder:coders',
                'clist:api:latest:index']

    def location(self, item):
        return reverse(item)


class StandingsSitemap(BaseSitemap):
    limit = 1000

    def items(self):
        return Contest.objects.filter(n_statistics__gt=0).order_by('-end_time', '-id')

    def priority(self, contest):
        return round(0.7 + (0.2 if 'medal' in contest.info.get('fields', []) else 0.0), 2)

    def lastmod(self, contest):
        return contest.updated

    def location(self, contest):
        return reverse('ranking:standings', args=(slug(contest.title), contest.pk))


class UpdatedStandingsSitemap(StandingsSitemap):
    priority = 0.6

    def items(self):
        return super().items().order_by('-updated')


class AccountsSitemap(BaseSitemap):
    limit = 1000

    def items(self):
        return Statistics.objects.filter(place_as_int__lte=3).order_by('-created').select_related('account__resource')

    def priority(self, stat):
        return round(0.5 - 0.1 * (stat.place_as_int - 1) / 10 + (0.4 if 'medal' in stat.addition else 0.0), 2)

    def lastmod(self, stat):
        return stat.created

    def location(self, stat):
        return reverse('coder:account', args=(stat.account.key, stat.account.resource.host))


class ResourcesSitemap(BaseSitemap):
    max_priority = None

    def items(self):
        self.max_priority = Resource.priority_objects.aggregate(Max('priority'))['priority__max']
        return Resource.priority_objects.annotate(lastmod=SubqueryMax('contest__parsed_time'))

    def priority(self, resource):
        ret = resource.priority
        if self.max_priority:
            ret /= self.max_priority
        return ret

    def lastmod(self, resource):
        return resource.lastmod or resource.modified

    def location(self, resource):
        return reverse('clist:resource', args=(resource.host, ))


sitemaps = {
    'static': StaticViewSitemap,
    'standings': StandingsSitemap,
    'updated_standings': UpdatedStandingsSitemap,
    'accounts': AccountsSitemap,
    'resources': ResourcesSitemap,
}
