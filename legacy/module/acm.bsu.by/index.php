<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = 'https://acm.bsu.by/api/contests';
    $http_header = array('http_header' => array('content-type: application/json'), 'json_output' => true);
    $data = curlexec($url, NULL, $http_header);

    if (!isset($data['contests'])) {
        trigger_error('json = ' . json_encode($data), E_USER_WARNING);
        return;
    }

    foreach ($data['contests'] as $k => $c) {
        $title = $c['name'];
        $u = $c['link'];
        $standings_url = url_merge($url, $u);
        $registration_url = null;
        if (preg_match('#^(?P<title>.*)\[(?P<url>acm.bsu.by/[^\]]*)\]$#', $title, $match)) {
            $title = trim($match['title']);
            $u = url_merge($url, '//' . $match['url']);
            $registration_url = $u;
        } else {
            $u = url_merge($url, $u);
        }
        $contest = array(
            'title' => $title,
            'start_time' => $c['startTime'],
            'end_time' => $c['endTime'],
            'url' => $u,
            'standings_url' => $standings_url,
            'registration_url' => $registration_url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['id'],
        );
        $contests[] = $contest;
    }
?>
