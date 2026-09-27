import re

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException


class Statistic(BaseModule):
    STANDING_URL_FORMAT_ = "http://informatics.mccme.ru/mod/monitor/view.php?id={0.key}"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if not self.key:
            raise InitModuleException()

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = Statistic.STANDING_URL_FORMAT_.format(self)
        page = REQ.get(standings_url, time_out=12)

        result = {}
        header = None
        prob_pos = None

        for match in re.findall(r"<tr[^>]*>\n.*?<\/tr>", page, re.DOTALL):
            match = match.replace("&nbsp;", " ")

            member = None
            fields = []

            tds = re.finditer(r"<td[^>]*>.*(?:<\/td>)?", match)
            for i, td in enumerate(tds):
                td = td.group()
                value = re.sub(r"<[^>]*>", "", td).strip()

                attrs = dict(m.group("key", "value") for m in re.finditer(r'(?P<key>[a-z]*)="?(?P<value>[^">]*)', td))
                if "href" in attrs:
                    match = re.search(r"/user/.*id=(?P<id>[0-9]+)", attrs["href"])
                    if match:
                        member = match.group("id")
                if not header and prob_pos is None and attrs.get("rowspan") != "2":
                    prob_pos = i
                # value = attrs.get('title', value)
                # if 'href' in attrs:
                #     match = re.search('solutions/(?P<member>[^/]*)/', attrs['href'])
                #     if match:
                #         member = match.group('member')
                #         problem_names.append(i)
                fields.append(value)

            if not header:
                header = fields
                continue

            if prob_pos:
                header = header[:prob_pos] + fields + header[prob_pos + 1 :]
                prob_pos = 0
                continue

            if not member:
                raise ExceptionParseStandings("Not found member")

            row = dict(list(zip(header, fields)))

            r = result.setdefault(member, {})
            r["member"] = member
            r["place"] = row["Место"]
            r["attempts"] = row["Попыток"]
            # Match the exact Unicode text used by the source data.
            r["solving"] = row["Всего"]  # ruff: ignore[ambiguous-unicode-character-string]

            problems = r.setdefault("problems", {})
            for k, v in row.items():
                if v and re.match(r"^[A-Z]$", k):
                    problems[k] = {"result": v}
            if not problems:
                r.pop("problems")
        standings = {
            "result": result,
            "url": standings_url,
        }
        return standings
