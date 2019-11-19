#!/usr/bin/env python
# -*- coding: utf-8 -*-

from lxml import etree
from copy import deepcopy
from collections import OrderedDict


def merge_dicts(a, b):
    ret = deepcopy(a)
    for k, v in list(b.items()):
        ret[k] = ' '.join(ret.get(k, '').split(' ') + v.split(' ')).strip()
    return ret


class ParsedTableValue(object):

    def __init__(self, row, col, header):
        self.attrs = merge_dicts(header.attrs, merge_dicts(row.attrs, col.attrs))
        self.value = col.value
        self.column = col
        self.row = row
        self.header = header

    def __str__(self):
        return self.value


class ParsedTableCol(object):

    def __init__(self, col):
        self.attrs = dict(list(col.items()))
        texts = col.itertext()
        texts = [t.strip() for t in texts]
        texts = [t for t in texts if len(t)]
        self.value = ' '.join(texts)
        self.node = col

    def __str__(self):
        return f'attrs = {self.attrs}, value = {self.value}'


class ParsedTableRow(object):

    def __init__(self, row):
        self.attrs = dict(list(row.items()))
        self.columns = list(map(ParsedTableCol, iter(row)))
        self.node = row

    def __str__(self):
        return f'attrs = {self.attrs}, columns = {list(map(str, self.columns))}'


class ParsedTable(object):

    def __init__(self, html, xpath='//table//tr', as_list=False):
        self.as_list = as_list
        self.table = etree.HTML(html).xpath(xpath)
        self.iter_table = iter(self.table)
        self.header = ParsedTableRow(next(self.iter_table))

        rowspan = 1
        for c in self.header.columns:
            rowspan = max(rowspan, int(c.attrs.get('rowspan', 0)))

        for rs in range(2, rowspan + 1):
            nxt = next(self.iter_table)
            row = ParsedTableRow(nxt)
            iter_row = iter(row.columns)

            columns = []
            for c in self.header.columns:
                if rs > int(c.attrs.get('rowspan', 0)):
                    for cs in range(int(c.attrs.get('colspan', 1))):
                        columns.append(next(iter_row))
                else:
                    columns.append(c)
            self.header.columns = columns

        columns = []
        for c in self.header.columns:
            for cs in range(int(c.attrs.get('colspan', 1))):
                columns.append(c)
        self.header.columns = columns

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            nxt = next(self.iter_table)
            row = ParsedTableRow(nxt)
            if len(row.columns) == len(self.header.columns):
                break

        kv = []
        for h, r in zip(self.header.columns, row.columns):
            k = h.value
            v = ParsedTableValue(row, r, h)
            kv.append((k, v))

        if self.as_list:
            return kv

        ret = OrderedDict()
        for k, v in kv:
            if k in ret:
                if not isinstance(ret[k], list):
                    ret[k] = [ret[k]]
                ret[k].append(v)
            else:
                ret[k] = v
        return ret
