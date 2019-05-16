<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://www.dmoj.ca/api/contest/list";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $prefix_contest = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST) . "/contest/";
    $json = curlexec($URL, NULL, array("json_output" => true));
    foreach ($json as $key => $data) {
        if (!isset($data["start_time"]) || !$data["start_time"]) {
            continue;
        }
        $contests[] = array(
            'start_time' => $data['start_time'],
            'duration' => $data['time_limit'],
            'end_time' => $data['end_time'],
            'title' => $data['name'],
            'url' => $prefix_contest . $key,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $key
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
