<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $preparers = array();
    foreach (['', '&order=UPDATE_TIME_DESC'] as $params) {
        $url = $URL . $params;
        $page = curlexec($url);
        preg_match_all(
            '#<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>.*?Prepared\s*by[^<]*<a[^>]*href="/profile/(?P<preparer>[^"]*)/?"[^>]*>#s',
            $page,
            $matches,
            PREG_SET_ORDER,
        );
        foreach ($matches as $match) {
            $preparers[$match['key']] = $match['preparer'];
        }
    }
    if (!count($preparers)) {
        trigger_error('preparers not found', E_USER_WARNING);
    }

    $url = 'https://codeforces.com/api/contest.list?gym=true&lang=en';

    $json = curlexec($url, NULL, array('json_output' => true));
    if (!is_array($json)) {
        return;
    }
    if (strpos($url, 'gym=true') === false) {
        trigger_error("Not found gym in $url", E_USER_WARNING);
        return;
    }
    if ($json['status'] != 'OK') {
        $json_str = print_r($json, true);
        trigger_error("status = {$json['status']}, json = $json_str", E_USER_WARNING);
        return;
    }

    if (isset($_GET['parse_full_list'])) {
        $contest_ids = array();
        foreach ($json['result'] as $c) {
            $contest_ids[] = $c['id'];
        }
    } else {
        $contest_ids = array_keys($preparers);
    }

    $authors = array();
    $chunks = array_chunk($contest_ids, 3);
    foreach ($chunks as $index => $chunk) {
        $url = 'https://mirror.codeforces.com/contests/' . implode(',', $chunk);
        $page = curlexec($url);

        preg_match_all(
            '#<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>[^<]*<td[^>]*>.*?</td>[^<]*<td[^>]*>(?P<authors>.*?)</td>.*?</tr>#s',
            $page,
            $matches,
            PREG_SET_ORDER,
        );
        foreach ($matches as $match) {
            $k = $match['key'];
            if (preg_match_all('#<a[^>]*href="/profile/(?<handle>[^"]*)/?"[^>]*>(?P<name>.*?)</a>#', $match['authors'], $m)) {
                $authors[$k] = $m['handle'];
            } else {
                $authors[$k] = array();
            }
        }

        preg_match_all(
            '#<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>.*?Prepared\s*by[^<]*<a[^>]*href="/profile/(?P<preparer>[^"]*)/?"[^>]*>#s',
            $page,
            $matches,
            PREG_SET_ORDER,
        );
        foreach ($matches as $match) {
            $preparers[$match['key']] = $match['preparer'];
        }
        if (ISCLI) {
            progress_bar($index + 1, count($chunks));
        }
    }

    if (count($authors) != count($preparers)) {
        trigger_error("Number of authors " . count($authors) . " is equal to number of preparers " . count($preparers), E_USER_WARNING);
    }

    $n_skipped = 0;
    foreach ($json['result'] as $c) {
        $unchanged = array();
        if (isset($c['startTimeSeconds'])) {
            $start_time = $c['startTimeSeconds'];
        } else {
            if (!empty($c['season'])) {
                list($year, $_) = explode('-', $c['season']);
                $start_time = strtotime("$year-09-03");
            } else if (preg_match('#(?P<year>^[0-9]{4}\b|\b[0-9]{4}$)#', $c['name'], $match)) {
                $year = $match['year'];
                $start_time = strtotime("$year-09-03");
            } else {
                $start_time = null;
            }
            if ($start_time === null || $start_time > time()) {
                $start_time = time() - $c['durationSeconds'];
                $start_time = $start_time - $start_time % 3600;
                $unchanged[] = 'start_time';
                $unchanged[] = 'end_time';
            }
        }
        $title = $c['name'];
        if (isset($preparers[$c['id']])) {
            $title .= '. ' . $preparers[$c['id']];
        } else {
            $n_skipped += 1;
            continue;
        }

        $contest = array(
            'start_time' => $start_time,
            'duration' => $c['durationSeconds'] / 60,
            'title' => $title,
            'url' => 'https://codeforces.com/gym/' . $c['id'],
            'host' => $HOST,
            'key' => $c['id'],
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'unchanged' => $unchanged,
            'skip_check_time' => true,
        );

        if (isset($authors[$c['id']])) {
            $contest['info'] = array('writers' => $authors[$c['id']]);
        }

        $contests[] = $contest;
    }
    if (ISCLI) {
        echo "Skipped $n_skipped contests\n";
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
