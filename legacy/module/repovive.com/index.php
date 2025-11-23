<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$page = curlexec($URL);

$page = preg_replace('#\\\#', '', $page);
$page = preg_replace('#"\$D#', '"', $page);

preg_match_all(
    '#
    "id":"(?P<key>[^"]*)",[^}]*
    "title":"(?P<title>[^"]*)",[^}]*
    "startDate":"(?P<start_time>[^"]*)",[^}]*
    "endDate":"(?P<end_time>[^"]*)",[^}]*
    #sx',
    $page,
    $matches,
    PREG_SET_ORDER,
);

foreach ($matches as &$match) {
    $contests[] = [
        "start_time" => $match["start_time"],
        "end_time" => $match["end_time"],
        "title" => $match["title"],
        "url" => $URL,
        "key" => $match["key"],
        "host" => $HOST,
        "timezone" => $TIMEZONE,
        "rid" => $RID,
    ];
}
