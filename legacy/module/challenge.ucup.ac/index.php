
<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . "/../../config.php";

$page = curlexec($URL);

preg_match_all(
    '#
    <ol[^>]*>.*?
    <[^>]*class="[^"]*contest__date[^"]*"[^/]*data-timestamp="(?P<timestamp>[^"]*)".*?
    <[^>]*class="[^"]*contest__title[^"]*"[^>]*>\s*<a[^>]*href="(?P<link>[^"]*/(?P<key>[^"/]+)/?)"[^>]*>(?P<title>[^<]*)</a>\s*</[^>]*>.*?
    <[^>]*class="[^"]*icon-schedule[^"]*"[^>]*>(?:\s*<[^>]*>)*\s*(?P<duration>[^<]*hour[^<]*)\s*</[^>]*>
    #six',
    $page,
    $matches,
    PREG_SET_ORDER,
);

foreach ($matches as $_ => $match) {
    $url = url_merge($URL, $match["link"]);
    $contests[] = [
        "start_time" => $match["timestamp"],
        "duration" => $match["duration"],
        "title" => $match["title"],
        "url" => $url,
        "key" => $match["key"],
        "host" => $HOST,
        "timezone" => $TIMEZONE,
        "rid" => $RID,
    ];
}
