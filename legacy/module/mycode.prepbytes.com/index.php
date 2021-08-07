<?php
    require_once dirname(__FILE__) . '/../../config.php';


    $url = 'https://server.prepbytes.com/api/contest/getContestList';
    $response = curlexec($url, "", array("json_output" => 1));
    if (!isset($response['data']) || !isset($response['code']) || $response['code'] != 200) {
        trigger_error('json = ' . json_encode($response), E_USER_WARNING);
        return;
    }

    foreach ($response['data'] as $k => $cs) {
        foreach ($cs as $c) {
            $title = $c['name'];
            $key = $c['contestId'];
            $url = url_merge($URL, '/contest/' . $key);

            if (isset($c['rated']) && $c['rated']) {
                $title .= '. Rated';
            }

            $contests[] = array(
                'start_time' => $c['startAt'],
                'end_time' => $c['endAt'],
                'duration' => $c['duration'],
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $key,
                'info' => array('parse' => $c),
            );
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
