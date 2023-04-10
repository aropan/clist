<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $schedule_page = curlexec($URL);

    preg_match_all('#<tr>.*?</tr>#s', $schedule_page, $rows, PREG_SET_ORDER);
    $headers = false;
    foreach ($rows as $row) {
        preg_match_all('#<t[hd][^>]*>(.*?)</t[hd]>#s', $row[0], $cols);
        if ($headers === false) {
            $headers = array_map('strtolower', $cols[1]);
            continue;
        }

        $values = $cols[1];
        foreach ($values as &$value) {
            if (preg_match('#<a[^>]*href="(?P<href>[^"]*)"[^>]*>#', $value, $match)) {
                $value = $match['href'];
            }
            $value = preg_replace('#<[^?]*>.*$#', '', $value);
            $value = trim($value);
        }
        $min_count = min(count($headers), count($values));
        $c = array_combine(
            array_slice($headers, 0, $min_count),
            array_slice($values, 0, $min_count),
        );

        $title = "Stage {$c['stage']}: " . trim($c['contest']);
        $date = $c['date'];

        if (strpos($date, 'TBD') !== false) {
            continue;
        }

        $parts = explode('.', $date);
        if (strlen($parts[0]) == 4) {
            $parts = array_reverse($parts);
        }
        $date = implode('.', $parts);

        $start_time = $date . ' 05:00 UTC';
        $end_time = $date . ' 23:00 UTC';
        $duration = '05:00';
        $key = $c['date'];

        $contest = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'duration' => $duration,
            'title' => trim($title),
            'url' => $c['announcement'] ?: $URL,
            'standings_url' => $c['scoreboard'],
            'key' => $key,
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );

        $contests[] = $contest;
    }
?>
