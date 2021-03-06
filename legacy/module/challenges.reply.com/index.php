<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);

    preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*class="[^"]*(code_challenge|hs_challenge)[^"]*"[^>]*>#', $page, $matches);

    foreach ($matches['url'] as $url) {
        $url = url_merge($URL, $url);
        $page = curlexec($url);

        if (!preg_match('#<div[^>]*class="subtitle"[^>]*>(?:\s*<[^>]*>)*(?P<title>[^<]+)</#', $page, $match)) {
            continue;
        }

        $title = ucwords(strtolower($match['title']));

        if (!preg_match('#<[^>]*>CHALLENGE DAY</[^>]*>\s*<[^>]*>\s*(?P<date>[0-9/]*)[^0-9]*(?P<date_start_time>[^-\s]*)[-\s]*(?P<date_end_time>[^-\s]*)[-\s]*(?P<timezone>[^<\s*]*)#', $page, $match)) {
            continue;
        }

        $date = str_replace('/', '.', $match['date']);
        $contests[] = array(
            'start_time' => $date . ' ' . $match['date_start_time'] . ' ' . $match['timezone'],
            'end_time' => $date . ' ' . $match['date_end_time'] . ' ' . $match['timezone'],
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
        );
    };

    if (DEBUG) {
        print_r($contests);
    }
?>
