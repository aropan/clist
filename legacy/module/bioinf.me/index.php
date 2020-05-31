<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    $page = preg_replace('/<br[^>]*>/', ' ', $page);
    $page = preg_replace('/\n/', ' ', $page);
    $page = preg_replace('/\s+/', ' ', $page);

    preg_match_all('#
        <div[^>]*field="title[^>]*>[^/]*
            <strong>(?P<title>[^<]*)</strong>
        (?:</[^>]*>)*[\s\n]*
        <div[^>]*field="desc[^>]*>[^/]*
            <div[^>]*>(?P<timing>[^<]*)</div>
        #x', $page, $matches, PREG_SET_ORDER);

    foreach ($matches as $m) {
        $title = $m['title'];
        if (!preg_match('#(?P<duration>[0-9]+\s+\w+)(?P<start_date>.*?[0-9]+)(?:[^0-9]*(?P<end_date>[0-9]+))?,\s*(?P<year>[0-9]{4})#', $m['timing'], $match)) {
            continue;
        }
        $year = $match['year'];
        $start_time = $match['start_date'] . " 11:59" . $year;
        if (!empty($match['end_date'])) {
            $end_time = preg_replace('#[0-9]+#', $match['end_date'], $start_time, 1);
            $duration = '';
        } else {
            $end_time = '';
            $duration = $match['duration'];
        }

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'duration' => $duration,
            'title' => $title,
            'url' => $URL,
            'host' => $HOST,
            'key' => $title . ' ' . $year,
            'rid' => $RID,
            'timezone' => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
