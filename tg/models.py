from pyclist.models import BaseModel
from django.db import models
from true_coders.models import Coder
from django.contrib.postgres.fields import JSONField


class Chat(BaseModel):
    chat_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    title = models.CharField(max_length=100, blank=True, null=True)
    name = models.TextField(blank=True, null=True)
    secret_key = models.CharField(max_length=20, blank=True, null=True)
    last_command = JSONField(default=dict, blank=True)
    is_group = models.BooleanField(default=False)
    coders = models.ManyToManyField(Coder, blank=True, related_name='chats')

    def __str__(self):
        return "%s#%s" % (self.coder_id, self.chat_id)

    def get_group_name(self):
        return "%s@%s" % (self.chat_id, self.title)


class History(BaseModel):
    LIMIT_BY_CHAT = 7
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE)
    message = JSONField()

    def __str__(self):
        return "Histroy %s" % (self.chat)

    def save(self, *args, **kwargs):
        q = History.objects.filter(chat=self.chat).order_by('created')
        count = q.count()
        if count > self.LIMIT_BY_CHAT:
            for o in q[0:count - self.LIMIT_BY_CHAT]:
                o.delete()
        super(History, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = 'History'
        ordering = ['-created']
