<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$year = date("Y");
$prev_year = $year - 1;
$next_year = $year + 1;
for ($year = $prev_year; $year <= $next_year; $year++) {
    $resource_url = "https://$year.andgein.ru/";
    $url = strtr($URL, array('${resource_url}' => $resource_url));
    $contest_data = curlexec($url, NULL, ["json_output" => true]);
    if (!is_array($contest_data)) {
        continue;
    }
    $page = curlexec($resource_url);
    $RESOURCE_URL = $resource_url;
    if (preg_match('#<link[^>]*rel="icon"[^>]*type="image/png"[^>]*href="(?P<href>[^"]*)"#', $page, $match)) {
        $RESOURCE_ICON_URL = url_merge($url, $match['href']);
    } else {
        $RESOURCE_ICON_URL = NULL;
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
}
