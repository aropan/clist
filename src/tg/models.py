from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from pyclist.models import BaseModel
from ranking.models import Account
from true_coders.models import Coder


class Chat(BaseModel):
    chat_id = models.CharField(max_length=100, blank=True, null=True)
    thread_id = models.TextField(blank=True, null=True, default=None)
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    title = models.CharField(max_length=100, blank=True, null=True)
    name = models.TextField(blank=True, null=True)
    secret_key = models.CharField(max_length=20, blank=True, null=True)
    last_command = models.JSONField(default=dict, blank=True)
    is_group = models.BooleanField(default=False)
    coders = models.ManyToManyField(Coder, blank=True, related_name='chats')
    accounts = models.ManyToManyField(Account, blank=True, related_name='chats')
    settings = models.JSONField(default=dict, blank=True)

    discussions = GenericRelation(
        'clist.Discussion',
        content_type_field='where_type',
        object_id_field='where_id',
        related_query_name='where_telegram_chat',
    )

    def __str__(self):
        return "%s Chat#%s" % (self.title or self.name or self.chat_id, self.id)

    def save(self, *args, **kwargs):
        if not self.thread_id:
            self.thread_id = None
        super().save(*args, **kwargs)

    def get_group_name(self):
        return "%s@%s" % (self.chat_id, self.title)

    def get_notification_method(self):
        ret = f'telegram:{self.chat_id}'
        if self.thread_id:
            ret += f':{self.thread_id}'
        return ret

    class Meta:
        unique_together = ['chat_id', 'thread_id']

    def update_coders_or_accounts(self):
        coders, accounts = list(self.coders.all()), list(self.accounts.all())
        for subscription in self.subscription_set.all():
            subscription.coders.set(coders)
            subscription.accounts.set(accounts)


@receiver(m2m_changed, sender=Chat.coders.through)
@receiver(m2m_changed, sender=Chat.accounts.through)
def update_coders_or_accounts(sender, instance, reverse, pk_set, action, **kwargs):
    if not action.startswith('post_'):
        return
    if reverse:
        for chat in Chat.objects.filter(pk__in=pk_set):
            chat.update_coders_or_accounts()
    else:
        instance.update_coders_or_accounts()


class History(BaseModel):
    LIMIT_BY_CHAT = 7
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE)
    message = models.JSONField()

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
