<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://binarysearch.com/api/contests';
    $json = curlexec($url, null, array("http_header" => array('content-type: application/json'), "json_output" => 1));

    if (!isset($json['contests']) || !isset($json['eduContests'])) {
        print_r($json);
        trigger_error("Wrong json response", E_USER_WARNING);
        return;
    }
    $data_contests = array_merge($json['contests'], $json['eduContests']);
    foreach ($data_contests as $c) {
        if (empty($c['starting'])) {
            continue;
        }

        $contests[] = array(
            'start_time' => $c['starting'],
            'duration' => $c['contestDuration'] / 60.0,
            'title' => $c['name'],
            'url' => 'https://binarysearch.com/room/' . $c['uniqueSlug'],
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['id'],
            'info' => array('parse' => $c),
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
