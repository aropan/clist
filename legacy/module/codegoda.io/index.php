<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = $URL;
    $contest_page = curlexec($url);

    preg_match_all('#<[^>]*class="twae-title"[^>]*>(?P<title>[^<]*)</[^>]*>\s*<[^>]*class="twae-description"[^>]*>(?:<[^/>]*>)*(?P<description>[^<]*)</#', $contest_page, $matches, PREG_SET_ORDER);

    foreach ($matches as $match) {
        $date = $match['title'];
        $date = str_replace('ICT', 'Asia/Bangkok', $date);
        $title = $match['description'];

        if (strpos($date, '-') !== false) {
            $times = preg_split('#\s*-\s*#', $date, 2);
            $start_time = $times[0];
            $end_time = $times[1];

            $times = preg_split('#\s+#', $start_time);
            $prefix_time = implode(' ', array_slice($times, 0, -1));
            $start_time = $times[count($times) - 1];

            $times = preg_split('#\s+#', $end_time);
            $end_time = $times[0];
            $suffix_time = implode(' ', array_slice($times, 1));

            $start_time = $prefix_time . ' ' . $start_time . ' ' . $suffix_time;
            $end_time = $prefix_time . ' ' . $end_time . ' ' . $suffix_time;
        } else {
            $start_time = $date;
            $end_time = $date;
        }

        $year = date('Y', strtotime($start_time));
        $title = 'Codegoda ' . $year . '. ' . $title;

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title,
            'url' => $URL,
            'key' => slugify($title),
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
    }
?>
