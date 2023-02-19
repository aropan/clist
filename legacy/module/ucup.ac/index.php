<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $schedule_page = curlexec($URL);

    $u = '/results';
    $result_page = curlexec($u);

    preg_match_all('#<a[^>]*href="(?P<url>[^"]*/scoreboard/[0-9]+)"[^>]*>(?P<desc>[^<]*)</a>#', $result_page, $matches, PREG_SET_ORDER);
    $standings_urls = array();
    foreach ($matches as $standings) {
        $parts = explode(':', $standings['desc']);
        $name = trim(end($parts));
        $standings_urls[$name] = $standings['url'];
    }

    preg_match_all('#
        <tr>\s*
        <td[^>]*>\s*(?P<date>[0-9.]*)\s*</td>\s*
        <td[^>]*>\s*(?P<title>[^<]*)\s*</td>\s*
        #x',
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

        $standings_url = false;
        foreach ($standings_urls as $name => $url) {
            if (strpos($title, $name) !== false) {
                $standings_name = $name;
                $standings_url = $url;
                break;
            }
        }
        if ($standings_url) {
            unset($standings_urls[$standings_name]);
        }


        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'duration' => $duration,
            'title' => trim($title),
            'url' => $URL,
            'standings_url' => $standings_url,
            'key' => $key,
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
    }
?>
