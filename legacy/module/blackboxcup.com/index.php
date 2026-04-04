<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$contest_data = curlexec($URL, NULL, ["json_output" => true]);
if (!is_array($contest_data)) {
    return;
}
$contests[] = [
    "start_time" => $contest_data["start_time"],
    "end_time" => $contest_data["finish_time"],
    "title" => $contest_data["name"],
    "url" => $contest_data["link"],
    "standings_url" => $contest_data["scoreboard_link"],
    "key" => strval($contest_data["id"]),
    "host" => $HOST,
    "timezone" => $TIMEZONE,
    "rid" => $RID,
];
