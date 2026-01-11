#!/usr/bin/env python3


import xml.etree.ElementTree as ET

import tqdm


def parse_int(s):
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_xml(standings_xml):
    root = ET.fromstring(standings_xml)
    contest = root.find('contest')
    sessions = contest.findall('session')

    ret = {}

    has_score = all('score' in session.attrib for session in sessions)
    if any(parse_int(session.attrib.get('solved')) and not parse_int(session.attrib.get('score'))
           for session in sessions):
        has_score = False

    for session in tqdm.tqdm(sessions):
        party = session.attrib['party'].strip()
        problems = ret.setdefault(party, {})
        for problem in session.findall('problem'):
            letter = problem.attrib['alias']
            scoring = has_score and 'score' in problem.attrib
            n_attempt = 0
            accepted = False
            time = None
            verdict = None
            score = None
            language = None
            for run in problem.findall('run'):
                v = (run.attrib.get('outcome') or '').lower()
                if v == 'compilation-error':
                    continue
                n_attempt += 1
                time_sec = int(run.attrib['time']) // 1000
                run_time = f'{time_sec // 60}:{time_sec % 60:02d}'
                if scoring:
                    if 'score' in run.attrib:
                        run_score = int(run.attrib['score'])
                        if score is None or run_score > score:
                            language = run.attrib.get('language-id')
                            score = run_score
                            time = run_time
                else:
                    accepted = run.attrib['accepted'] == 'yes'
                    time = run_time
                    language = run.attrib.get('language-id')
                    verdict = v
                    if accepted:
                        break
            if attempts := parse_int(problem.attrib['attempts']):
                n_attempt = attempts
            if n_attempt == 0:
                continue

            if scoring:
                if score is None:
                    score = int(problem.attrib['score'])
                result = score
            else:
                if accepted:
                    result = '+' if n_attempt == 1 else f'+{n_attempt - 1}'
                    result = f'?{result}'
                elif verdict == 'undefined':
                    result = f'?{n_attempt}'
                    verdict = None
                else:
                    result = f'-{n_attempt}'

            p = problems.setdefault(letter, {})
            p['result'] = result
            if time:
                p['time'] = time
            if verdict:
                verdict = ''.join(s[0] for s in verdict.upper().split('-'))
                p['verdict'] = 'AC' if accepted else verdict
            if language:
                p['language'] = language
    return ret
