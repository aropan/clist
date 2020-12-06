from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from clist.models import Contest
from ranking.models import Statistics
from clist.templatetags.extras import slug


class BaseSitemap(Sitemap):
    protocol = 'https'
    abstract = True


class StaticViewSitemap(BaseSitemap):
    priority = 1
    changefreq = 'daily'

    def items(self):
        return ['clist:main', 'clist:resources', 'ranking:standings_list', 'clist:problems', 'coder:coders']

    def location(self, item):
        return reverse(item)


class StandingsSitemap(BaseSitemap):
    priority = 0.7
    limit = 1000

    def items(self):
        return Contest.objects.filter(n_statistics__gt=0).order_by('-updated')

    def lastmod(self, contest):
        return contest.updated

    def location(self, contest):
        return reverse('ranking:standings', args=(slug(contest.title), contest.pk))


class AccountsSitemap(BaseSitemap):
    limit = 1000

    def items(self):
        return Statistics.objects.filter(place_as_int__lte=10).order_by('-created').select_related('account__resource')

    def priority(self, stat):
        return round(0.5 - 0.1 * (stat.place_as_int - 1) / 10, 2)

    def lastmod(self, stat):
        return stat.created

    def location(self, stat):
        return reverse('coder:account', args=(stat.account.key, stat.account.resource.host))


sitemaps = {
    'static': StaticViewSitemap,
    'standings': StandingsSitemap,
    'accounts': AccountsSitemap,
}
