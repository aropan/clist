<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $types = array('currentOrUpcoming', 'past');

    foreach ($types as $type) {
        $response = array();
        for ($page = 1; !$response || $page <= $response['data']['contests']['lastPage']; ++$page) {
            $url = 'https://lightoj.com/api/v1/contests?page=' . $page . '&contestType=' . $type;
            $response = curlexec($url, null, array("http_header" => array('content-type: application/json'), "json_output" => 1));

            if (!isset($response['data']['contests']['data'])) {
                var_dump($response);
                trigger_error("Unusual response", E_USER_WARNING);
                break;
            }

            foreach ($response['data']['contests']['data'] as $c) {
                $title = $c['contestTitleStr'] . ' [' . $c['contestVisibilityStr'] . ', ' . $c['contestTypeStr'] . ', ' . $c['contestParticipationTypeStr'] . ']';
                $contests[] = array(
                    'start_time' => $c['contestStartTimestamp'],
                    'end_time' => $c['contestEndTimestamp'],
                    'title' => $title,
                    'url' => url_merge($URL, '/contest/' . $c['contestHandleStr']),
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $c['contestId'],
                );
            }

            if ($type == 'past' && !isset($_GET['parse_full_list'])) {
                break;
            }
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
