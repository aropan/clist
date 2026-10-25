# ruff: file-ignore[mutable-class-default]

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("clist", "0198_resource_medal_win_equals_gold"),
        ("ranking", "0168_alter_account_account_type"),
        ("true_coders", "0077_filter_window_duration"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="account",
            index=models.Index(
                condition=models.Q(rating__isnull=False),
                fields=["resource", "account_type", "rating"],
                name="account_resource_type_rating",
            ),
        ),
    ]
