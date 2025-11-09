from django.db import models


class AccountType(models.IntegerChoices):
    USER = 1, 'User'
    UNIVERSITY = 2, 'University'
    TEAM = 3, 'Team'