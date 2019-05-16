<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://ctftime.org/calendar/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = "RU";
    if (!isset($TIMEZONE)) $TIMEZONE = "Europa/Moscow";
    if (!isset($contests)) $contests = array();

    $authorization = get_calendar_authorization();
    if (!$authorization) {
        die("no authorization");
    }
    $calendar = "ctftime@gmail.com";
    $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar) . "/events?timeMin=" . urlencode(date('c', time() - 3 * 24 * 60 * 60));
    $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));
    if (!isset($data["items"])) {
        print_r($data);
        return;
    }
    foreach ($data["items"] as $item) {
        if (!preg_match("#https?[^\s]*$#", $item["description"], $matches)) {
            trigger_error("No found url in ${item["description"]}", E_USER_WARNING);
        }
        $url = $matches[0];

        preg_match("#(?<key>[A-Za-z0-9_ ]+)/?$#", $url, $match);
        $key = $match["key"];

        $contests[] = array(
            "start_time" => $item["start"]["dateTime"],
            "end_time" => $item["end"]["dateTime"],
            "title" => $item["summary"],
            "url" => $url,
            "host" => $HOST,
            "rid" => $RID,
            "timezone" => $TIMEZONE,
            "key" => $key
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
