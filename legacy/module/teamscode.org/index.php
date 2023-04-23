<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $contests_page = curlexec($URL);

    preg_match_all('#<a[^>]*href="/contests/(?P<key>[^"/]*)"#', $contests_page, $matches);
    $keys = array_unique($matches['key']);
    foreach ($keys as $contest_key) {
        $contest_url = url_merge($URL, '/contests/' . $contest_key);
        $contest_page = curlexec($contest_url);
        preg_match('#<h2[^>]*>(?P<title>[^<]*)</h2>(?:[^<]*<div[^>]*>)*(?P<time>[^<]*)#', $contest_page, $match);
        $title = trim($match['title']);
        $time = trim($match['time']);
        $time = preg_replace('#\s*\bat\b.*$#', '', $time);

        if (preg_match('#\s+-\s+#', $time)) {
            $times = preg_split('#\s+-\s+#', $time, 2);
            $start_time = preg_split('#\s+#', $times[0]);
            $end_time = preg_split('#\s+#', $times[1]);
            if (count($start_time) < count($end_time)) {
                $end_time = array_slice($end_time, 0, count($start_time));
            } else {
                $common_prefix = 3;
                $intersection = count($start_time) - $common_prefix;
                $end_time = array_merge(array_slice($start_time, 0, $common_prefix), array_slice($end_time, 0, $intersection));
            }
            $start_time = implode(' ', $start_time);
            $end_time = implode(' ', $end_time);
        } else {
            $start_time = $time;
            $end_time = $time;
        }

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title,
            'url' => $contest_url,
            'key' => $contest_key,
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
    }
?>
