<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $data = curlexec($URL, null, array("json_output" => 1));
    $max_id = 0;

    $add_contest = function($c) {
        if (!isset($c['id'])) {
            return;
        }
        global $HOST, $RID, $TIMEZONE, $contests;
        $key = intval($c['id']);
        $contests[] = array(
            'start_time' => $c['starts'],
            'end_time' => $c['ends'],
            'title' => $c['name'],
            'url' => 'https://sort-me.org/contest/' . $key,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $key,
        );
    };

    foreach ($data as $c) {
        $key = intval($c['id']);
        $max_id = max($max_id, $key);
        $add_contest($c);
    }

    if (isset($_GET['parse_full_list'])) {
        while ($max_id-- >= 1) {
            $u = 'https://api.sort-me.org/getContestById?id=' . $max_id;
            $c = curlexec($u, null, array("json_output" => 1));
            $add_contest($c);
        }
    }
?>
