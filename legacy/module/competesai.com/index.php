<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$data = curlexec($URL, NULL, ["json_output" => true]);
if (!is_array($data)) {
    trigger_error("$HOST: " . $data, E_USER_WARNING);
    return;
}

foreach ($data as $_ => $contest_data) {
    if (!isset($contest_data["timelineConfig"])) {
        continue;
    }
    $url = url_merge($HOST_URL, $contest_data["slug"]);
    $contests[] = [
        "start_time" => $contest_data["timelineConfig"]["startDate"],
        "end_time" => $contest_data["timelineConfig"]["endDate"],
        "title" => $contest_data["name"],
        "url" => $url,
        "standings_url" => $url . '?tab=leaderboard',
        "key" => $contest_data["id"],
        "host" => $HOST,
        "timezone" => $TIMEZONE,
        "rid" => $RID,
    ];
}
