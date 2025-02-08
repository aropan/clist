from modeltranslation.translator import TranslationOptions, register

from clist.models import Problem


@register(Problem)
class ProblemTranslationOptions(TranslationOptions):
    fields = ('name', )
