from django.contrib.sitemaps import Sitemap
from django.db.models.functions import Greatest
from django.urls import reverse
from django.utils.timezone import now as timezone_now
from sql_util.utils import SubqueryMax

from clist.models import Contest, Resource
from true_coders.models import Coder


class BaseSitemap(Sitemap):
    protocol = "https"
    abstract = True
    limit = 1000


class StaticViewSitemap(BaseSitemap):
    def items(self):
        items = [
            "clist:main",
            "clist:resources",
            "clist:resources_account_ratings",
            "clist:resources_country_ratings",
            "ranking:standings_list",
            "clist:problems",
            "coder:coders",
            "clist:links",
            "clist:api:latest:index",
        ]
        return items[: self.limit]

    def location(self, item):
        return reverse(item)


class StandingsSitemap(BaseSitemap):
    def items(self):
        return (
            Contest.objects
            .filter(n_statistics__gt=0, invisible=False, end_time__lt=timezone_now())
            .annotate(freshness=Greatest("end_time", "created"))
            .order_by("-freshness", "-id")
            .values_list("id", "slug", "parsed_time", "end_time", named=True)
        )[: self.limit]

    def lastmod(self, contest):
        return contest.parsed_time or contest.end_time

    def location(self, contest):
        return reverse("ranking:standings", args=(contest.slug, contest.id))


class CodersSitemap(BaseSitemap):
    value_limit = 700

    def items(self):
        fields = ("id", "username", "lastmod", "modified")
        candidates = Coder.objects.filter(n_contests__gte=10).annotate(lastmod=SubqueryMax("account__last_activity"))
        items = {}
        for queryset, count in (
            (candidates.order_by("-n_contests", "-id"), self.value_limit),
            (candidates.order_by("-created", "-id"), self.limit),
        ):
            for coder in queryset.values_list(*fields, named=True)[:count]:
                items.setdefault(coder.id, coder)
                if len(items) == self.limit:
                    return list(items.values())
        return list(items.values())

    def lastmod(self, coder):
        return coder.lastmod or coder.modified

    def location(self, coder):
        return reverse("coder:profile", args=(coder.username,))


class ResourcesSitemap(BaseSitemap):
    def items(self):
        resources = (
            Resource.objects
            .filter(n_contests__gt=0)
            .only("id", "host", "modified")
            .annotate(lastmod=SubqueryMax("contest__parsed_time"))
        )
        return resources[: self.limit]

    def lastmod(self, resource):
        return resource.lastmod or resource.modified

    def location(self, resource):
        return reverse("clist:resource", args=(resource.host,))


sitemaps = {
    "static": StaticViewSitemap,
    "standings": StandingsSitemap,
    "coders": CodersSitemap,
    "resources": ResourcesSitemap,
}
