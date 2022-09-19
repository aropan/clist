#!/usr/bin/env python3


import os
import sys
sys.path.append(os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', '..'))  # noqa
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pyclist.settings')  # noqa

import tqdm
import fire
import xml.etree.ElementTree as ET
import django
django.setup()  # noqa

from ranking.models import Statistics


def main(
    contest_id,
    standings_xml,
    season,
):
    tree = ET.parse(standings_xml)
    root = tree.getroot()
    contest = root.find('contest')
    sessions = contest.findall('session')
    for session in tqdm.tqdm(sessions):
        party = session.attrib['party']
        key = f'{party} {season}'

        statistic = Statistics.objects.get(contest_id=contest_id, account__key=key)
        for problem in session.findall('problem'):
            letter = problem.attrib['alias']
            n_attempt = 0
            accepted = False
            time = None
            for run in problem.findall('run'):
                verdict = run.attrib['outcome']
                if verdict == 'compilation-error':
                    continue
                n_attempt += 1
                time_sec = int(run.attrib['time']) // 1000
                time = f'{time_sec // 60}:{time_sec % 60:02d}'
                accepted = run.attrib['accepted'] == 'yes'
                if accepted:
                    break
            if n_attempt == 0:
                continue

            if accepted:
                result = '+' if n_attempt == 1 else f'+{n_attempt - 1}'
            else:
                result = f'-{n_attempt}'
            stat_result = statistic.addition['problems'].get(letter, {}).get('result')
            assert stat_result == result

            if not accepted:
                statistic.addition['problems'].get(letter)['time'] = time
                statistic.save()


if __name__ == '__main__':
    fire.Fire(main)
