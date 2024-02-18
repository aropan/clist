#!/usr/bin/env python
# -*- coding: utf-8 -*-


class BaseException(Exception):

    def __init__(self, *args):
        super().__init__(*args)

    def __str__(self):
        return f'{self.__class__.__name__}: {super().__str__()}'


class InitModuleException(BaseException):
    pass


class ExceptionParseStandings(BaseException):
    pass


class ExceptionParseAccounts(BaseException):
    pass
