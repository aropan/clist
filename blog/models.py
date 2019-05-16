from pyclist.models import BaseModel, models
from django_markdown.models import MarkdownField


class EntryQuerySet(models.QuerySet):
    def published(self):
        return self.filter(publish=True)


class Entry(BaseModel):
    title = models.CharField(max_length=200)
    body = MarkdownField()
    slug = models.SlugField(max_length=200, unique=True)
    publish = models.BooleanField(default=True)

    objects = EntryQuerySet.as_manager()

    def __str__(self):
        return "%s" % (self.title)

    class Meta:
        verbose_name = 'Blog Entry'
        verbose_name_plural = 'Blog Entries'
        ordering = ['-created']
