<?php
    require_once dirname(__FILE__) . '/../../config.php';

    for ($page = 1;; $page += 1) {
        $url = "https://practiceapi.geeksforgeeks.org/api/v1/events/?type=contest&page_number=$page&sub_type=all";

        $response = curlexec($url, null, array("json_output" => 1));
        if (!isset($response['results'])) {
            trigger_error('json = ' . json_encode($response), E_USER_WARNING);
            return;
        }

        $results = array_merge(...array_values($response['results']));
        $nothing = true;

        foreach ($results as $k => $c) {
            $nothing = false;
            if (isset($c['name'])) {
                $title = $c['name'];
            } else if (isset($c['title'])) {
                $title = $c['title'];
            } else {
                trigger_error("Not found name in contest = " . json_encode($c), E_USER_WARNING);
                continue;
            }

            $contests[] = array(
                'start_time' => $c['start_time'],
                'end_time' => $c['end_time'],
                'title' => $title,
                'url' => url_merge($URL, "/contest/${c["slug"]}/"),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $c['slug'],
            );
        }

        if (!isset($_GET['parse_full_list']) || $nothing) {
            break;
        }
    }
?>

