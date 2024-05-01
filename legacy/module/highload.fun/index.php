<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $data = curlexec($URL, null, array("json_output" => 1));
    if ($data['result'] !== 'OK') {
        trigger_error("Failed to fetch data, result = '${data['result']}', error = '${data['error']}'", E_USER_WARNING);
        return;
    }

    foreach ($data['data'] as $_ => $contest) {
        foreach ($contest['rounds'] as $_ => $round) {
            $contests[] = array(
                'start_time' => $round['round_from'],
                'end_time' => $round['round_to'],
                'title' => $contest['caption'] . '. ' . $round['caption'],
                'url' => url_merge($HOST_URL, "/timed_competitions/${contest['id']}"),
                'standings_url' => url_merge($HOST_URL, "/timed_competitions/${contest['id']}/leaderboard/${round['id']}/"),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $contest['id'] . '/' . $round['id'],
            );
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
