<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://toph.co/contests";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();


    $page = curlexec($URL);

    preg_match_all('#<a[^>]*href="?(?P<url>[^">]*)"?[^>]*>\s*<h2[^>]*>(?P<title>[^<]*)</h2>\s*</a>#', $page, $matches, PREG_SET_ORDER);

    foreach ($matches as $match) {
        $url = url_merge($URL, $match['url']);
        $title = $match['title'];

        $page = curlexec($url);
        preg_match('#will start <[^>]*data-time=(?P<start_time>[0-9]+)[^>]*>.*?will run for <strong>(?P<duration>[^<]*)</strong>#', $page, $match);

        $path = explode('/', trim($url, '/'));

        $contests[] = array(
            'start_time' => $match['start_time'],
            'duration' => $match['duration'],
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => end($path)
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
