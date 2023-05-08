<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page_size = 50;
    $response = null;
    for ($n_page = 1; empty($response) || $n_page <= $response['pagesCount']; $n_page += 1) {
        $page_url = "$URL?page=$n_page&page_size=$page_size";
        $response = curlexec($page_url, null, array('json_output' => true));
        if (!isset($response['data'])) {
            trigger_error("Unexpected response", E_USER_WARNING);
            break;
        }

        foreach ($response['data'] as $c) {
            $title = htmlspecialchars_decode($c['title']);
            if ($c['isRated']) {
                $title .= '. Rated';
            }
            $contests[] = array(
                'start_time' => $c['startTime'],
                'end_time' => $c['finishTime'],
                'title' => $title,
                'url' => url_merge($HOST_URL, '/competitions/contests/contest/' . $c['id']),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $c['id'],
                'info' =>  array('parse' => $c),
            );
        }

        if (!isset($_GET['parse_full_list'])) {
            break;
        }
    }
?>
