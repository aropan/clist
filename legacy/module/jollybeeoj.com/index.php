<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'http://jollybeeoj.com/tools/contest/data';
    $json = curlexec($url, "", array('json_output' => true));
    if (is_array($json)) {
        foreach ($json as $data) {
            $ok = true;
            foreach (array('startTime', 'endTime', 'title', 'contestId') as $key) {
                if (!isset($data[$key]) || empty($data[$key])) {
                    $ok = false;
                    break;
                }
            }
            if (!$ok) {
                continue;
            }
            $contests[] = array(
                'title' => $data['title'],
                'start_time' => $data['startTime'] / 1000,
                'end_time' => $data['endTime'] / 1000,
                'url' => "https://jollybeeoj.com/contest/${data['contestId']}/about",
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $data['contestId']
            );
        }
    } else {
        trigger_error("No get json data from $url", E_USER_WARNING);
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
