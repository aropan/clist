<?php

global $contests, $HOST, $TIMEZONE, $RID;

$page = curlexec($URL);

preg_match_all('#<script[^>]*src="(?P<href>[^"]*)"[^>]*>#i', $page, $script_matches, PREG_SET_ORDER);
foreach ($script_matches as $script_match) {
    $script_url = url_merge($URL, $script_match['href']);
    $script_page = curlexec($script_url);
    preg_match_all('/children:[^]]*"(?P<start_time>[^"]*) - (?P<end_time>[^"]*)"[^]})]*href:"http[^"]*timeanddate.com[^"]*worldclock[^"]*\?(?P<params>[^"]*)"/', $script_page, $matches, PREG_SET_ORDER);
    foreach ($matches as $match) {
        parse_str($match['params'], $params);
        if (!isset($params['msg']) || !preg_match('/round|contest/i', $params['msg'])) {
            ;
            continue;
        }
        [$start_time, $end_time] = hydrate_datetime([$match['start_time'], $match['end_time']], 'right');
        $duration = (strtotime($end_time) - strtotime($start_time)) / 60;

        $title = trim($params['msg']);
        $contests[] = [
            'start_time' => $start_time,
            'duration' => $duration,
            'title' => $title,
            'url' => $URL,
            'key' => slugify($title),
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        ];
    }
}
