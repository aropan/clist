<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://www.battlecode.org/contestants/calendar/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = "RU";
    if (!isset($TIMEZONE)) $TIMEZONE = "America/New_York";
    if (!isset($contests)) $contests = array();

    $authorization = get_calendar_authorization();
    if (!$authorization) {
        return;
    }

    $calendar = "mitbattlecode@gmail.com";
    $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar) . "/events?timeMin=" . urlencode(date("c", time() - 24 * 60 * 60));
    $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));
    if (!isset($data["items"])) {
        print_r($data);
        return;
    }
    foreach ($data["items"] as $item)
    {
        if (!isset($item["status"]) || !isset($item["summary"]) || $item["status"] != "confirmed") {
            continue;
        }
        $title = $item["summary"];
        $title = ucfirst($title);
        $ok = false;
        foreach (array("tournament", "final", "deadline", "submission", "begin") as $msg) {
            if (strpos(strtolower($title), $msg) !== false) {
                $ok = true;
                break;
            }
        }
        if (!$ok) {
            continue;
        }

        $start_time = $item["start"][isset($item["start"]["dateTime"])? "dateTime" : "date"];
        $end_time = $item["end"][isset($item["end"]["dateTime"])? "dateTime" : "date"];
        $year = substr($start_time, 0, 4);
        $title = preg_replace('/\s*\([^\)]*\)\s*$/', '', $title);
        $contests[] = array(
            "start_time" => $start_time,
            "end_time" => $end_time,
            "title" => $title,
            "url" => $URL,
            "host" => $HOST,
            "rid" => $RID,
            "timezone" => "UTC",
            "key" => "$title $year"
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
