<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $parse_full_list = isset($_GET['parse_full_list']);

    $page = curlexec($URL);

    if (!preg_match_all('#<a[^>]*href="(?P<url>/programmers/challenges/(?P<key>[^/]*)/?)"[^>]*>#', $page, $matches, PREG_SET_ORDER)) {
        return;
    }

    foreach ($matches as $c) {
        $url = $c['url'];
        $page = curlexec($url);

        if (!preg_match('#<div[^>]*class="header"[^>]*>[^<]*<div[^>]*>[^<]*<h2[^>]*>(?P<title>[^<]*)</h2>[^/]*>\s*Start date:\s*(?P<start_time>[^<]*)#i', $page, $match)) {
            return;
        }

        $start_time = strtotime(preg_replace('#[[:space:]]+#', ' ', $match['start_time']));
        $title = trim($match['title']);
        $title = str_replace('&#x27;', "'", $title);

        $contests[] = array(
            'start_time' => $start_time,
            'duration' => '24:00',
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $c['key'],
        );

        if (!$parse_full_list && $start_time + 24 * 60 * 60 < time()) {
            break;
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
