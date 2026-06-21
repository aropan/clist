<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$contest_page = curlexec($URL);

preg_match_all("#<div[^>]*>(?P<title>[^>]*(?:qual|final)[^<]*)(?P<desc>.*?)</div>#is", $contest_page, $matches, PREG_SET_ORDER);

foreach ($matches as $match) {
    $desc = preg_split("#<[^>]*>#", $match["desc"]);
    $desc = array_values(array_filter($desc));
    $start_time = $desc[0];
    $start_time = preg_replace("#([0-9]+)[\\D\\W\\S]+[0-9]+,#", "\\1,", $start_time);
    $duration = $desc[1];
    if (strpos($duration, ",")) {
        [$time, $duration] = explode(",", $duration);
        if (strpos($time, ":") === false) {
            $time = preg_replace("#([0-9]+) #", "\\1:00 ", $time);
        }
        $start_time = "$start_time, $time";
    }
    $year = date("Y", strtotime($start_time));
    $title = "Midnight Code Cup $year. " . trim($match["title"]);
    $contests[] = [
        "title" => $title,
        "start_time" => trim($start_time),
        "duration" => trim($duration),
        "url" => $URL,
        "key" => slugify($title),
        "host" => $HOST,
        "timezone" => $TIMEZONE,
        "rid" => $RID,
    ];
}
