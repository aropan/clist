<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $parse_full_list = isset($_GET['parse_full_list']);

    $page = curlexec($URL);

    if (!preg_match_all('#<a[^>]*href="(?P<url>/programmers/challenges/(?P<key>[^/]*)/?)"[^>]*>#', $page, $matches, PREG_SET_ORDER)) {
        return;
    }

    $timedelta_day = 24 * 60 * 60;
    $timedelta_week = 7 * $timedelta_day;
    foreach ($matches as $c) {
        $url = $c['url'];
        $page = curlexec($url);

        if (!preg_match('#<div[^>]*class="header"[^>]*>[^<]*<div[^>]*>[^<]*<h2[^>]*>(?P<title>[^<]*)</h2>[^/]*>\s*Start date:\s*(?P<start_time>[^<]*)#i', $page, $match)) {
            return;
        }
        $start_challenge = boolval(preg_match('#START CHALLENGE#', $page));

        $start_time = strtotime(preg_replace('#[[:space:]]+#', ' ', $match['start_time']));
        $title = trim($match['title']);

        $now = time();
        $end_time = max($now + $timedelta_week, $start_time + 3 * $timedelta_week);
        if (!$start_challenge) {
            $end_time = min($end_time, $now);
        }
        $end_time = intdiv(($end_time - $start_time), $timedelta_week) * $timedelta_week + $start_time;
        if (!$start_challenge && isset($prev_start_time)) {
            $end_time = min($end_time, $prev_start_time - $timedelta_day);
        }
        $prev_start_time = $start_time;

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['key'],
        );

        if (!$parse_full_list) {
            break;
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
