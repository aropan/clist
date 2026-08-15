from django.conf import settings
from django.core.management.base import BaseCommand

from tg.bot import Bot


class Command(BaseCommand):
    help = "Ensure the configured Telegram bot webhook points to this application"

    def handle(self, *args, **options):
        if not settings.TELEGRAM_TOKEN:
            self.stdout.write("Telegram is disabled")
            return

        bot = Bot()
        webhook_info = bot.get_webhook_info()
        if webhook_info.url == bot.webhook_url:
            self.stdout.write("Telegram webhook is already configured")
            return

        bot.webhook()
        self.stdout.write(self.style.SUCCESS("Telegram webhook updated"))
