<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $min_start_time = INF;
    $limit_start_time = time() - 90 * 24 * 60 * 60;
    for ($n_page = 1; $limit_start_time < $min_start_time || isset($_GET['parse_full_list']); $n_page += 1) {
        $url = 'https://api.tlx.toki.id/v2/contests?page=' . $n_page;
        $json = curlexec($url, NULL, array("json_output" => 1));

        if (!isset($json['data'])) {
            trigger_error('json = ' . json_encode($json), E_USER_WARNING);
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
                'url' => 'https://tlx.toki.id/contests/' . $c['slug'],
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
