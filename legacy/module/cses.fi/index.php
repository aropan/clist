<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $contests_page = curlexec($URL);
    preg_match_all('#<a[^>]*href="(?P<url>/(?P<key>[^/]*)/[^"]+)"[^>]*>[^<]*Go to contest[^<]*</a>#', $contests_page, $matches, PREG_SET_ORDER);
    foreach ($matches as $match) {
        $key = $match['key'];
        $url = $match['url'];
        $page = curlexec($url);
        preg_match('#<div[^>]*class="[^"]*title[^"]*"[^>]*>\s*<h1[^>]*>(?P<title>[^<]*)</h1>#', $page, $match);
        $title = $match['title'];
        preg_match_all('#<b[^>]*>(?P<key>[^<]*)</b>\s*<span[^>]*>(?P<value>[^<]*)</span>#', $page, $values_matches, PREG_SET_ORDER);
        $values = array();
        foreach ($values_matches as $value_match) {
            $values[$value_match['key']] = $value_match['value'];
        }
        $start_time = $values['Start:'];
        $end_time = $values['End:'];
        if (strtoupper($start_time) == 'N/A') {
            continue;
        }

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title,
            'url' => $url,
            'key' => $key,
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
    }
?>
