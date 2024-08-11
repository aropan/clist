<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = 0;
    $data = null;
    $stop = false;
    $limit = 25;
    $now = time();
    while (!$stop && (!$data || $page < $data['data']['total_pages'])) {
        $page += 1;
        $url = "https://api.codingninjas.com/api/v3/public_section/contest_list?page=$page";
        $data = curlexec($url, null, array("json_output" => 1));

        if (!isset($data['data']['events'])) {
            trigger_error('data = ' . json_encode($data), E_USER_WARNING);
            break;
        }

        foreach ($data['data']['events'] as $c) {
            $start_time = $c['event_start_time'];
            if (!isset($_GET['parse_full_list']) && $start_time < $now) {
                $limit -= 1;
                if (!$limit) {
                    $stop = true;
                }
            }
            $end_time = max($start_time, $c['event_end_time']);

            $contests[] = array(
                'start_time' => $start_time,
                'end_time' => $end_time,
                'title' => $c['name'],
                'url' => "$URL/{$c['slug']}",
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $c['slug'],
            );
        }
    }
?>
