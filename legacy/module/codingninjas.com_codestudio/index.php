<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://api.codingninjas.com/api/v3/public_section/contest_list';
    $data = curlexec($url, null, array("json_output" => 1));

    foreach ($data['data']['events'] as $c) {
        $contests[] = array(
            'start_time' => $c['event_start_time'],
            'end_time' => $c['event_end_time'],
            'title' => $c['name'],
            'url' => "$URL/${c['slug']}",
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['slug'],
        );
    }
?>
