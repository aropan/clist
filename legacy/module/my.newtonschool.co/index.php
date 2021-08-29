<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $api_url = 'https://my.newtonschool.co/api/v1/contests/list/';

    $seen = array();
    foreach (array('false', 'true') as $past) {
        $url = "$api_url?past=$past&offset=0&limit=10";

        while ($url) {
            if (isset($seen[$url])) {
                break;
            }
            $seen[$url] = true;

            $response = curlexec($url, null, array("json_output" => 1));

            if (!isset($response['results'])) {
                trigger_error('json = ' . json_encode($response), E_USER_WARNING);
                return;
            }

            foreach ($response['results'] as $_ => $c) {
                $title = $c['title'];
                $fa = $c['filtering_assignment'];

                $contests[] = array(
                    'start_time' => $fa['start_timestamp'] / 1000,
                    'end_time' => $fa['end_timestamp'] / 1000,
                    'title' => $fa['title'],
                    'url' => url_merge($api_url, '/course/' . $c['hash']. '/assignment/' . $fa['hash'] . '/dashboard/'),
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $c['hash']. '/' . $fa['hash'],
                );
            }
            if ($past == 'true' && !isset($_GET['parse_full_list'])) {
                break;
            }
            $url = $response['next'];
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
