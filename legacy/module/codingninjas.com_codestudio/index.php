<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $URL = 'https://www.codingninjas.com/codestudio/contests';
    $page = curlexec($URL);

    preg_match_all('#
        <[^>]*>(?P<status>[^<]*)<[^>]*>(?:\s*<[^a][^>]*>)*
        <h4[^>]*>(?P<title>[^<]*)</h4>\s*
        <[^>]*>(?P<time>[^<]*)<[^>]*>(?:[^<]*<[^a][^>]*>)*
        <a[^>]*href="(?P<url>[^"]*/contests/[^"]*)"[^>]*>
        #x', $page, $matches, PREG_SET_ORDER);

    $year = date('Y');
    $now = time();
    $prev = $now;
    $month = 30 * 24 * 60 * 60;

    foreach ($matches as $c) {
        $is_past = trim(strtolower($c['status'])) == 'past';
        $url = url_merge($URL, $c['url']);
        $time = $c['time'];
        if (strpos($time, ' | ') !== false) {
            list($date, $time) = explode(' | ', $time);
        } else {
            $date = '';
        }
        if (preg_match('#\((?P<timezone>[^\)]*)\)$#', $time, $match)) {
            $time = substr($time, 0, strlen($time) - strlen($match[0]));
            $timezone = $match['timezone'];
        } else {
            $timezone = '';
        }
        $timezone = str_replace('CUT', 'UTC', $timezone);
        list($start_time, $end_time) = explode(' - ', $time);
        $start_time = trim($date . " " . $start_time . " " . $timezone);
        $end_time = trim($date . " " . $end_time . " " . $timezone);

        if (!preg_match('#/contests/(?P<key>[^/]+)#', $url, $match)) {
            continue;
        }
        $key = $match['key'];

        if (empty($date)) {
            if ($is_past) {
                $y = $year;
                while ($y > 0 && strtotime($start_time . ', ' . $y) - 2 * $month > $prev) {
                    $y -= 1;
                }
            } else {
                $y = $year;
                while ($y < 5000 && strtotime($start_time . ', ' . $y) < $now) {
                    $y += 1;
                }
            }
            if ($y == 0 || $y == 5000) {
                continue;
            }
            $start_time .= ', ' . $y;
            while (strtotime($end_time. ', ' . $y) < strtotime($start_time)) {
                $y += 1;
            }
            $end_time .= ', ' . $y;
        }
        $prev = strtotime($start_time);

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $c['title'],
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $key,
        );
    }
?>
