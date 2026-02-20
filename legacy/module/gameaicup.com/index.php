<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$contests_data = curlexec($URL, NULL, ["json_output" => true]);
if (!is_array($contests_data)) {
    return;
}

foreach ($contests_data as $contest_data) {
    $name = strtolower($contest_data["name"]);
    if ($name == "sandbox") {
        $slug = "sandbox";
    } else if ($name == "round 1") {
        $slug = "round1";
    } else if ($name == "round 2") {
        $slug = "round2";
    } else if ($name == "final round") {
        $slug = "final";
    }

    $contests[] = [
        "start_time" => $contest_data["startTime"] / 1000,
        "end_time" => $contest_data["endTime"] / 1000,
        "title" => $contest_data["name"],
        "url" => url_merge($URL, "/$slug-overview"),
        "key" => $contest_data["_id"],
        "host" => $HOST,
        "timezone" => $TIMEZONE,
        "rid" => $RID,
    ];
}
