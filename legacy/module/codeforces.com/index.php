<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $authors = array();
    $urls = array();
    $url = $URL;
    foreach (array('?complete=true', '?complete=true&lang=ru') as $params) {
        $url = url_merge($URL, $params);
        for (; $url && !in_array($url, $urls);) {
            $urls[] = $url;
            $page = curlexec($url);
            preg_match_all(
                '#<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>[^<]*<td[^>]*>.*?</td>[^<]*<td[^>]*>(?P<authors>.*?)</td>.*?</tr>#s',
                $page,
                $matches,
                PREG_SET_ORDER
            );
            $end_times = array();
            foreach ($matches as $match) {
                $k = $match['key'];
                if (isset($authors[$k])) {
                    continue;
                }
                if (preg_match_all('#<a[^>]*>(?P<name>.*?)</a>#', $match['authors'], $m)) {
                    $names = array_map(function($n) { return strip_tags($n); }, $m['name']);
                    $authors[$k] = $names;
                } else {
                    $authors[$k] = array();
                }
            }
            if (!isset($_GET['parse_full_list'])) {
                break;
            }
            preg_match_all('#<[^>]*class="[^"]*page-index[^"]*"[^>]*>\s*<a[^>]*href="(?P<href>[^"]*)">#', $page, $matches, PREG_SET_ORDER);
            foreach ($matches as $m) {
                $u = url_merge($url, $m['href']);
                if (!in_array($u, $urls)) {
                    $url = $u;
                    break;
                }
            }
        }
    }

    $url = 'http://codeforces.com/api/contest.list?lang=en';
    $json = curlexec($url, NULL, array('json_output' => true));

    $json['status'] == 'OK' or trigger_error("status = '${json['status']}' for $url");
    foreach ($json['result'] as $c) {
        $title = $c['name'];
        if (!isset($c['startTimeSeconds'])) {
            continue;
        }

        $contest = array(
            'start_time' => $c['startTimeSeconds'],
            'duration' => $c['durationSeconds'] / 60,
            'title' => $title,
            'url' => 'http://codeforces.com/contests/' . $c['id'],
            'host' => $HOST,
            'key' => $c['id'],
            'rid' => $RID,
            'timezone' => $TIMEZONE
        );

        if (isset($authors[$c['id']])) {
            $contest['info'] = array('writers' => $authors[$c['id']]);
        }

        if (isset($end_times[$c['id']])) {
            $contest['end_time'] = $end_times[$c['id']];
        }

        $contests[] = $contest;
    }
?>
