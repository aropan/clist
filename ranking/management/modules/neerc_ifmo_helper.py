#!/usr/bin/env python3


import tqdm
import xml.etree.ElementTree as ET


def parse_xml(standings_xml):
    root = ET.fromstring(standings_xml)
    contest = root.find('contest')
    sessions = contest.findall('session')

    ret = {}
    for session in tqdm.tqdm(sessions):
        party = session.attrib['party'].strip()
        has_score = 'score' in session.attrib
        problems = ret.setdefault(party, {})
        for problem in session.findall('problem'):
            letter = problem.attrib['alias']
            scoring = has_score and 'score' in problem.attrib
            n_attempt = 0
            accepted = False
            time = None
            verdict = None
            score = 0
            for run in problem.findall('run'):
                v = run.attrib.get('outcome')
                if v == 'compilation-error':
                    continue
                n_attempt += 1
                time_sec = int(run.attrib['time']) // 1000
                run_time = f'{time_sec // 60}:{time_sec % 60:02d}'
                if scoring:
                    run_score = int(run.attrib['score'])
                    if run_score > score:
                        score = run_score
                        time = run_time
                else:
                    accepted = run.attrib['accepted'] == 'yes'
                    time = run_time
                    if accepted:
                        break
                    if v:
                        verdict = ''.join(s[0] for s in v.upper().split('-'))
            if n_attempt == 0:
                continue

            if scoring:
                result = score
            else:
                if accepted:
                    result = '+' if n_attempt == 1 else f'+{n_attempt - 1}'
                else:
                    result = f'-{n_attempt}'

            p = problems.setdefault(letter, {})
            p['result'] = result
            if time:
                p['time'] = time
            if verdict:
                p['verdict'] = verdict
    return ret
