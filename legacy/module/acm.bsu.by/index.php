<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = 'https://acm.bsu.by/api/contests';
    $http_header = array('http_header' => array('content-type: application/json'), 'json_output' => true);
    $data = curlexec($url, NULL, $http_header);

    foreach ($data['contests'] as $k => $c) {
        $u = url_merge($url, $c['link']);
        $contest = array(
            'title' => $c['name'],
            'start_time' => $c['startTime'],
            'end_time' => $c['endTime'],
            'url' => $u,
            'standings_url' => $u,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['id'],
        );

        $contests[] = $contest;
    }
?>
