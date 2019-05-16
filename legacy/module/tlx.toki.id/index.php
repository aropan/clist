<?php
    require_once dirname(__FILE__) . '/../../config.php';

    if (!isset($URL)) $URL = 'https://tlx.toki.id/competition/contests';
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $min_start_time = INF;
    $limit_start_time = time() - 90 * 24 * 60 * 60;
    for ($n_page = 1; $limit_start_time < $min_start_time; $n_page += 1) {
        $url = 'https://uriel.tlx.toki.id/api/v2/contests?page=' . $n_page;
        $json = curlexec($url, NULL, array("json_output" => 1));

        if (!isset($json['data'])) {
            trigger_error('json = ' . json_encode($json));
            return;
        }

        if (count($json['data']['page']) == 0) {
            break;
        }

        foreach ($json['data']['page'] as $c) {
            $start_time = intval($c['beginTime']) / 1000;
            $min_start_time = min($start_time, $min_start_time);
            $contests[] = array(
                'start_time' => $start_time,
                'duration' => intval($c['duration']) / 60000.0,
                'title' => $c['name'],
                'url' => 'https://tlx.toki.id/competition/contests/' . $c['id'],
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $c['id']
            );
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
