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
                if (preg_match_all('#<a[^>]*href="/profile/(?<handle>[^"]*)/?"[^>]*>(?P<name>.*?)</a>#', $match['authors'], $m)) {
                    $authors[$k] = $m['handle'];
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
    if (!count($authors)) {
        trigger_error('Authors not found', E_USER_WARNING);
    }

    $url = 'https://codeforces.com/api/contest.list?lang=en';
    $json = curlexec($url, NULL, array('json_output' => true));
    if (!is_array($json)) {
        return;
    }
    $json['status'] == 'OK' or trigger_error("status = '{$json['status']}' for $url");
    $global_rounds_stage_year = false;
    foreach ($json['result'] as $c) {
        $title = $c['name'];
        if (!isset($c['startTimeSeconds'])) {
            continue;
        }
        $url = 'https://codeforces.com/contests/' . $c['id'];

        if (preg_match('/^Codeforces Global Round /', $title)) {
            $year = date('Y', $c['startTimeSeconds']);
            if (!$global_rounds_stage_year || $global_rounds_stage_year < $year) {
                $global_rounds_stage_year = $year;
                $global_rounds_url = null;
            }
            if ($global_rounds_stage_year == $year) {
                if (!$global_rounds_url) {
                    $global_rounds_url = $url;
                } else {
                    $global_rounds_url .= ',' . $c['id'];
                }
            }
        }

        $contest = array(
            'start_time' => $c['startTimeSeconds'],
            'duration' => $c['durationSeconds'] / 60,
            'title' => $title,
            'url' => $url,
            'key' => $c['id'],
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
        );

        if (isset($authors[$c['id']])) {
            $contest['info'] = array('writers' => $authors[$c['id']]);
        }

        if (isset($end_times[$c['id']])) {
            $contest['end_time'] = $end_times[$c['id']];
        }

        $contests[] = $contest;
    }

    if ($global_rounds_stage_year) {
        $contests[] = array(
            'start_time' =>  "$global_rounds_stage_year-01-01 12:00",
            'end_time' =>  "$global_rounds_stage_year-12-31 12:00",
            'title' => "Codeforces Global Rounds $global_rounds_stage_year",
            'url' => $global_rounds_url,
            'host' => $HOST,
            'key' => "codeforces-global-rounds-$global_rounds_stage_year",
            'info' => array('_inherit_stage' => true),
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
        );
    }
?>
