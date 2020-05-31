<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = curlexec($URL);
    preg_match_all('/<h3>(?P<title>[^<]*)<\/h3>\s*<p>\s*<span[^>]*>.*?Time:(?P<date>[^<\(]*)[^<]*/s', $page, $matches);
    foreach ($matches[0] as $i => $value) {
        $title = trim($matches['title'][$i]);
        $date = trim($matches['date'][$i]);
        $start_time = NULL;
        $end_time = NULL;
        if (preg_match('/(,\s*)?(?P<start_time>[0-9]+:[0-9]+)(?:-(?P<end_time>[0-9]+:[0-9]+))?$/', $date, $match)) {
            $start_time = $match['start_time'];
            $end_time = $match['end_time'];
            $date = substr($date, 0, strlen($date) - strlen($match[0]));
        }
        $date = preg_replace('/-[0-9]+,/', ',', $date);
        $date = preg_replace('/[^0-9]+$/', '', $date);
        $year = date('Y', strtotime($date));
        $start_time = $date . ($start_time && !empty($start_time)? ' ' . $start_time : '');
        $end_time = $end_time && !empty($end_time)? $date . ' ' . $end_time : $start_time;
        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title,
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $title . ' ' . $year
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
