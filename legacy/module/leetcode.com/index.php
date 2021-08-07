<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://leetcode.com/graphql';
    $postfields = '{"operationName":null,"variables":{},"query":"{\n  brightTitle\n  allContests {\n    containsPremium\n    title\n    cardImg\n    titleSlug\n    description\n    startTime\n    duration\n    originStartTime\n    isVirtual\n    company {\n      watermark\n      __typename\n    }\n    __typename\n  }\n}\n"}';
    $json = curlexec($url, $postfields, array("http_header" => array('content-type: application/json'), "json_output" => 1));

    if (!isset($json['data']) || !isset($json['data']['allContests'])) {
        trigger_error('json = ' . json_encode($json), E_USER_WARNING);
        return;
    }

    foreach ($json['data']['allContests'] as $c) {
        $contests[] = array(
            'start_time' => $c['originStartTime'],
            'duration' => $c['duration'] / 60.0,
            'title' => $c['title'],
            'url' => 'https://leetcode.com/contest/' . $c['titleSlug'],
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['titleSlug']
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
