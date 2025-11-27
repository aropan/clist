<?php

require_once dirname(__FILE__) . "/../../config.php";

function parse_season($base_url)
{
    global $RID, $HOST, $TIMEZONE, $contests;

    $seen = [];
    $stage_standings_url = "$base_url/rating";
    $rating_page = curlexec($stage_standings_url);
    preg_match_all(
        '#<th[^>]*>(?:\s*<[^/][^>]*>)*\s*<a[^>]*href="?(?P<href>[^"]*)"?[^>]*>(?P<title>[^<]*)</a>#s',
        $rating_page,
        $matches,
        PREG_SET_ORDER,
    );
    $standings = [];
    foreach ($matches as $stage => $th) {
        $standings_url = url_merge($stage_standings_url, $th["href"]);
        $parsed_url = parse_url($standings_url);
        $parsed_url["path"] = rtrim($parsed_url["path"], "/") . "/standings/";
        $standings_url = unparse_url($parsed_url);
        $standings[$stage] = ["standings_url" => $standings_url, "title" => $th["title"], "stage" => $stage];
    }

    $stage_url = $base_url;
    $schedule_page = curlexec($stage_url);

    if (!preg_match("#<h[12][^>]*>\s*season\s*(?P<season>[0-9]+)\b#i", $schedule_page, $match)) {
        return;
    }
    $season = $match["season"];

    $stage_start_time = null;
    $stage_end_time = null;

    preg_match_all("#<tr>.*?</tr>#s", $schedule_page, $rows, PREG_SET_ORDER);
    $headers = false;
    foreach ($rows as $row) {
        preg_match_all("#<t[hd][^>]*>(?P<values>.*?)</(?P<tag>t[hd])>#s", $row[0], $cols);
        if ($headers === false || $cols["tag"][0] == "th") {
            $headers = array_map("strtolower", $cols["values"]);
            continue;
        }

        $values = $cols["values"];
        foreach ($values as &$value) {
            if (preg_match('#<a[^>]*href="(?P<href>[^"]*)"[^>]*>#', $value, $match)) {
                $value = url_merge($stage_url, $match["href"]);
            }
            $value = preg_replace('#<[^?]*>.*$#', "", $value);
            $value = trim($value);
        }
        $min_count = min(count($headers), count($values));
        $c = array_combine(array_slice($headers, 0, $min_count), array_slice($values, 0, $min_count));

        if (!isset($c["stage"]) || !isset($c["contest"]) || !isset($c["date"])) {
            continue;
        }

        $stage_parts = preg_split("#[^a-z0-9]+#i", strtolower($c["stage"]));
        $stage_desc = "stage";
        if (count($stage_parts) > 1) {
            if (count($stage_parts) == 2 && $stage_parts[0] == "extra") {
                $stage_desc = $stage_parts[0] . " stage " . $stage_parts[1];
            } else {
                continue;
            }
        } else {
            $stage_desc .= " " . $c["stage"];
        }
        $stage_title = ucwords($stage_desc);

        $title = "The " . ordinal($season) . " Universal Cup. $stage_title: " . trim($c["contest"]);
        $date = $c["date"];

        if (strpos($date, "TBD") !== false) {
            continue;
        }

        if (strpos($date, "to") !== false) {
            $date = trim(explode("to", $date)[0]);
        }

        $parts = explode(".", $date);
        if (strlen($parts[0]) == 4) {
            $parts = array_reverse($parts);
        }
        $date = implode(".", $parts);

        // $season = date('Y', strtotime($date)) - 2022 + (date('m', strtotime($date)) >= 9? 1 : 0);
        $start_time = $date . " 05:00 UTC";
        $end_time = $date . " 23:00 UTC";
        $duration = "05:00";
        $stage_key = str_replace(" ", "-", $stage_desc);
        $key = "ucup-" . $season . "-" . $stage_key;
        $info = ["parse" => ["season" => "$season", "stage" => $stage_key]];

        $standings_url = isset($c["scoreboard"]) ? $c["scoreboard"] : null;
        $standings_stage = null;
        foreach ($standings as $stage => $info) {
            if (stripos($info["title"], $c["contest"]) === false) {
                continue;
            }
            if ($standings_stage === null || strlen($info["title"]) < strlen($standings_stage["title"])) {
                $standings_stage = $info;
            }
        }
        if ($standings_stage) {
            $standings_url = $standings_stage["standings_url"];
            unset($standings[$standings_stage["stage"]]);
        }

        $start_and_title = $start_time . " " . $c["stage"] . " " . trim($c["contest"]);
        if (isset($seen[$start_and_title])) {
            continue;
        }
        $seen[$start_and_title] = true;

        if ($stage_start_time === null) {
            $stage_start_time = $start_time;
        }
        $stage_end_time = $end_time;

        $contest = [
            "start_time" => $start_time,
            "end_time" => $end_time,
            "duration" => $duration,
            "title" => trim($title),
            "url" => isset($c["announcement"]) ? $c["announcement"] : $stage_url,
            "key" => $key,
            "info" => $info,
            "host" => $HOST,
            "timezone" => $TIMEZONE,
            "rid" => $RID,
        ];

        if ($standings_url) {
            $contest["standings_url"] = $standings_url;
        }

        $contests[] = $contest;
    }

    $two_weeks = 14 * 24 * 60 * 60;
    $stage_end_time = strtotime($stage_end_time) + $two_weeks;
    $contest = [
        "start_time" => $stage_start_time,
        "end_time" => $stage_end_time,
        "title" => "The " . ordinal($season) . " Universal Cup. Rating",
        "url" => $stage_url,
        "standings_url" => $stage_standings_url,
        "key" => "ucup-" . $season . "-rating",
        "info" => ["_inherit_stage" => true],
        "host" => $HOST,
        "timezone" => $TIMEZONE,
        "rid" => $RID,
    ];
    $contests[] = $contest;

    return $season;
}

$season = parse_season("https://ucup.ac/");
$prev_season = $season - 1;
parse_season("https://ucup.ac/archive/season$prev_season/");
