<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $schedule_page = curlexec($URL);

    preg_match_all('#
        <tr>\s*
        <td[^>]*>\s*(?P<date>[0-9.]*)\s*</td>\s*
        <td[^>]*>\s*(?P<title>[^<]*)\s*</td>\s*
        .*?
        </tr>
        #xs',
        $schedule_page,
        $matches,
        PREG_SET_ORDER,
    );

    foreach ($matches as $c) {
        $title = trim($c['title']);
        $date = $c['date'];
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
            'url' => $URL,
            'key' => $key,
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );

        if (preg_match('#<td[^>]*>\s*<a[^>]*href="(?P<href>[^"]*/scoreboard/[^"]*)"[^>]*>[^<]*</a>\s*</td>#', $c[0], $m)) {
            $standings_url = url_merge($URL, $m['href']);
            $contest['standings_url'] = $standings_url;
        }

        $contests[] = $contest;
    }
?>
