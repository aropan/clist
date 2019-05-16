<?php
    require_once dirname(__FILE__) . '/../../config.php';

    if (!isset($URL)) $URL = 'https://csacademy.com/contests/';
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $json = curlexec($URL, NULL, array("http_header" => array("X-Requested-With: XMLHttpRequest"), "json_output" => 1));

    unset($jcontests);
    foreach (array('contest', 'Contest') as $k) {
        if (isset($json['state'][$k])) {
            $jcontests = $json['state'][$k];
            break;
        }
    }

    if (!isset($jcontests)) {
        trigger_error("No get json data from $URL", E_USER_WARNING);
        return;
    }

    foreach ($jcontests as $data) {
        // if (!isset($data['editorialUrl'])) {
        //     continue;
        // }
        if (!isset($data['startTime'])
            || !isset($data['endTime'])
            || !isset($data['description'])
            || isset($data['systemGenerated'])
                && $data['systemGenerated'] == 1
                && preg_match('/\s*-\s*(interviews|algorithms)$/', $data['longName'])
            || preg_match('/Virtual.*contest.*contest.*[0-9]+/i', $data['longName'])
        ) {
            continue;
        }
        $contests[] = array(
            'start_time' => $data['startTime'],
            'end_time' => $data['endTime'],
            'title' => $data['longName'],
            'url' => "https://csacademy.com/contest/{$data['name']}/",
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $data['id']
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
