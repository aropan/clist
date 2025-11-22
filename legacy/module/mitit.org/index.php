<?php

global $contests, $HOST, $TIMEZONE, $RID;

$page = curlexec($URL);

preg_match_all('#<script[^>]*src="(?P<href>[^"]*)"[^>]*>#i', $page, $script_matches, PREG_SET_ORDER);
foreach ($script_matches as $script_match) {
    $script_url = url_merge($URL, $script_match['href']);
    $script_page = curlexec($script_url);

    if (!preg_match('#"(?P<title>[^"]*(?P<year>\b[0-9]{4}\b)[^"]*(?:contest|rounds?)) will take place on[^"]*"#i', $script_page, $match)) {
        continue;
    }
    $year = trim($match["year"]);
    $title = trim($match["title"]);

    if (!preg_match('#children:"[^"]*?(?P<day>\b[./0-9]+\b)[^"]*[^"]*\bcontest\b[^"]*\bday\b[^"]*"(?P<page>.*?)\}\)\]#si', $script_page, $match)) {
        continue;
    }
    $day = trim($match["day"]);
    $day = preg_replace('#[^0-9]+#', ".", $day);
    $day = implode(".", array_reverse(explode(".", $day)));

    preg_match_all('#children:"(?P<time>[^"]*)"[^\[\]]*"(?P<title>[^\[\]"]*\b(?:contest|round)\b[^\[\]"]*)"#si', $match["page"], $contest_matches, PREG_SET_ORDER);
    foreach ($contest_matches as $contest_match) {
        $subtitles = explode("+", $contest_match["title"]);
        foreach ($subtitles as $subtitle) {
            $subtitle = trim($subtitle);
            if (preg_match('#\bdiscussion\b#i', $subtitle)) {
                continue;
            }
            if (!preg_match('#\bcontest\b|\bround\b#i', $subtitle)) {
                continue;
            }
            $contest_title = $title . ". " . $subtitle;

            list($start_time, $end_time) = explode("-", $contest_match["time"]);
            $start_time = trim($start_time, ' :');
            $end_time = trim($end_time, ' :');
            $start_time = $day . "." . $year . " " . $start_time;
            $end_time = $day . "." . $year . " " . $end_time;

            $contests[] = [
                "start_time" => $start_time,
                "end_time" => $end_time,
                "title" => $contest_title,
                "url" => $URL,
                "key" => slugify($contest_title),
                "host" => $HOST,
                "timezone" => $TIMEZONE,
                "rid" => $RID,
            ];
        }
    }
}
