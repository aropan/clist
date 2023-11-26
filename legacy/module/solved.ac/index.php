<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $contests_url = $URL;
    $contests_page = curlexec($contests_url);

    preg_match('#<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<json>[^<]*)</script>#', $contests_page, $match);
    $data = json_decode($match['json'], true);
    $data = $data['props']['pageProps']['data'];

    foreach ($data as $_ => $contests_data) {
        foreach ($contests_data as $contest_data) {
            $title = $contest_data['title'];
            if (!empty($contest_data['divisionDisplayName'])) {
                $title .= '. ' . $contest_data['divisionDisplayName'];
            }
            $contests[] = array(
                'start_time' => $contest_data['startTime'],
                'end_time' => $contest_data['endTime'],
                'title' => $title,
                'url' => $contests_url,
                'key' => $contest_data['arenaId'],
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'info' => array('parse' => $contest_data),
                'rid' => $RID,
            );
        }
    }
?>
