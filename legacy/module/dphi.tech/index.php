<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $types = array('upcoming', 'active', 'past');

    foreach ($types as $type) {
        $limit = 100;
        $url = 'https://aiplanet.com/api/datathons/?list=' . $type . '&page=1&page_size=' . $limit . '&query=%7Bid,challenge_id,end_date,datathon_type,start_date,title,slug,url%7D';
        while ($url) {
            $response = curlexec($url, null, array("http_header" => array('content-type: application/json'), "json_output" => 1));

            if (!is_array($response) || !isset($response['results'])) {
                trigger_error("Not found events in $url", E_USER_WARNING);
                break;
            }

            foreach ($response['results'] as $c) {
                $cid = "{$c['challenge_id']}";

                $title = $c['title'];
                if ($c['datathon_type']) {
                    $title .= '. ' . ucfirst($c['datathon_type']);
                }

                $contests[] = array(
                    'start_time' => $c['start_date'],
                    'end_time' => $c['end_date'],
                    'title' => $title,
                    'url' => url_merge($URL, "/challenges/{$c['slug']}/$cid/"),
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $cid,
                );
            }

            if (!isset($response['next']) || $type == 'past' && !isset($_GET['parse_full_list'])) {
                break;
            }

            $url = $response['next'];
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
