#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
from collections import OrderedDict
from copy import deepcopy

from lxml import etree


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


class FakeTableCol(object):

    def __init__(self, value, attrs):
        self.value = value
        self.attrs = attrs

    def items(self):
        return self.attrs.items()

    def itertext(self):
        return [self.value]


class ParsedTableCol(object):

    def __init__(self, col):
        self.attrs = dict(list(col.items()))
        texts = col.itertext()
        texts = [t.strip() for t in texts]
        texts = [t for t in texts if len(t)]
        self.value = ' '.join(texts)
        self.node = col

    @property
    def colspan(self):
        return int(self.attrs.get('colspan', 1))

    @property
    def rowspan(self):
        return int(self.attrs.get('rowspan', 1))

    @property
    def rowspaned(self):
        return int(self.attrs.get('rowspaned', 1))

    def __str__(self):
        return f'attrs = {self.attrs}, value = {self.value}'


class ParsedTableRow(object):

    def __init__(self, row=None):
        if row is not None:
            self.attrs = dict(list(row.items()))
            self.columns = list(map(ParsedTableCol, iter(row)))
        else:
            self.attrs = {}
            self.columns = []
        self.node = row

    def __str__(self):
        return f'attrs = {self.attrs}, columns = {list(map(str, self.columns))}'


class ParsedTable(object):

    def __init__(
        self,
        html,
        xpath='//table//tr',
        as_list=False,
        with_duplicate_colspan=False,
        with_not_full_row=False,
        ignore_wrong_header_number=True,
        ignore_display_none=False,
        unnamed_fields=(),
        header_mapping=(),
        without_header=False,
        strip_empty_columns=False,
        default_header_rowspan=1,
    ):
        self.as_list = as_list
        self.with_duplicate_colspan = with_duplicate_colspan
        self.with_not_full_row = with_not_full_row
        self.table = etree.HTML(html).xpath(xpath)
        self.unnamed_fields = unnamed_fields
        self.unnamed_fields_idx = 0
        self.header_mapping = header_mapping
        self.ignore_wrong_header_number = ignore_wrong_header_number
        self.ignore_display_none = ignore_display_none
        self.without_header = without_header
        self.strip_empty_columns = strip_empty_columns
        self.init_iter(default_header_rowspan)
        self.last_row = None

    def init_iter(self, default_header_rowspan=1):
        self.n_rows = len(self.table) - 1
        self.iter_table = iter(self.table)
        if self.without_header:
            self.header = ParsedTableRow()
        else:
            self.header = ParsedTableRow(next(self.iter_table))

        rowspan = default_header_rowspan
        for c in self.header.columns:
            rowspan = max(rowspan, int(c.attrs.get('rowspan', 0)))

        for rs in range(2, rowspan + 1):
            nxt = next(self.iter_table)
            row = ParsedTableRow(nxt)
            iter_row = iter(row.columns)

            columns = []
            for c in self.header.columns:
                if rs > int(c.attrs.get('rowspan', 0)):
                    for cs in range(c.colspan):
                        col = next(iter_row)
                        col.attrs['_top_column'] = c
                        columns.append(col)
                else:
                    columns.append(c)
            self.header.columns = columns

        columns = []
        for c in self.header.columns:
            for cs in range(c.colspan):
                columns.append(c)
        self.header.columns = columns

    def __iter__(self):
        return self

    def __len__(self):
        return self.n_rows

    def __next__(self):
        while True:
            nxt = next(self.iter_table)
            row = ParsedTableRow(nxt)

            if self.last_row is not None:
                for index, c in enumerate(self.last_row.columns):
                    if c.rowspaned < c.rowspan:
                        c.attrs['rowspaned'] = str(c.rowspaned + 1)
                        row.columns.insert(index, c)

            if self.with_duplicate_colspan:
                row.columns = sum([[c] * c.colspan for c in row.columns], [])

            if self.ignore_display_none:
                row.columns = [c for c in row.columns if not re.search(r'display\s*:\s*none', c.attrs.get('style', ''))]

            while self.unnamed_fields_idx < len(self.unnamed_fields) and len(row.columns) > len(self.header.columns):
                field = self.unnamed_fields[self.unnamed_fields_idx]
                self.unnamed_fields_idx += 1

                column = ParsedTableCol(FakeTableCol(field.get('value', ''), field.get('attrs', {})))
                self.header.columns.append(column)

            if self.strip_empty_columns:
                while len(row.columns) > len(self.header.columns) and not row.columns[-1].value:
                    row.columns.pop(-1)

            self.last_row = row

            if len(row.columns) == len(self.header.columns):
                break

            if self.with_not_full_row and len(row.columns) < len(self.header.columns):
                break

            if not self.ignore_wrong_header_number:
                return row

        kv = []
        colspan = 0
        for h, r in zip(self.header.columns, row.columns):
            if self.with_duplicate_colspan and colspan > 0:
                colspan -= 1
                continue
            k = h.value
            if k in self.header_mapping:
                k = self.header_mapping[k]
            v = ParsedTableValue(row, r, h)
            kv.append((k, v))
            colspan = r.colspan - 1

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
