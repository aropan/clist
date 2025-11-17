<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$page = curlexec($URL);

if (!preg_match('#<a[^>]*href="([^"]*)"[^>]*>(?:\s*<[^>]*>)*the web#i', $page, $match)) {
    trigger_error("Failed to find contest link", E_USER_WARNING);
    return;
}

$contest_url = url_merge($URL, $match[1]);

$page = curlexec($contest_url);
if (!preg_match("#<h[^>]*>\s*the web\s*</h[^>]*>\s*<h[^>]*>[^<]*(?P<start_date>[0-9]{2}\.[0-9]{2}\.[0-9]{4})[^<]*</h[^>]*>#i", $page, $match)) {
    trigger_error("Failed to find contest start date", E_USER_WARNING);
    return;
}
$start_date = $match["start_date"];

if (!preg_match("#<title[^>]*>(?P<title>[^<]*)</title>#", $page, $match)) {
    trigger_error("Failed to find contest title", E_USER_WARNING);
    return;
}
$title = $match["title"];

if (!preg_match("#/(?P<key>[0-9]+(?:-[0-9]+)*)/?$#", $contest_url, $match)) {
    trigger_error("Failed to find contest key", E_USER_WARNING);
    return;
}
$contest_key = $match["key"];

$regex = "#<h[^>]*>\s*(?P<tag>\#[a-z/]*)\s*</[^>]*>(?:\s*<[^>]*>)*\s*(?P<start_time>[0-9]{1,2}:[0-9]{2})[^<]*</[^>]*>(?P<start_tz>[^<]*)<#";
if (!preg_match_all($regex, $page, $matches, PREG_SET_ORDER)) {
    trigger_error("Failed to find contest start time", E_USER_WARNING);
    return;
}

foreach ($matches as &$match) {
    $start_time = $match["start_time"];
    $start_tz = trim($match["start_tz"]);
    $start_time = $start_date . " " . $start_time . " " . $start_tz;
    $tag = $match["tag"];

    $contests[] = [
        "start_time" => $start_time,
        "duration" => $tag == "#school" ? "02:00" : "04:00",
        "title" => $title . " " . $tag,
        "url" => $contest_url,
        "key" => $contest_key . $tag,
        "host" => $HOST,
        "timezone" => $TIMEZONE,
        "rid" => $RID,
    ];
}

?>
