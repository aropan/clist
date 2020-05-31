<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = curlexec($URL);
    preg_match_all('/<li[^>]*>\s*<strong>(?P<title>[^:<]*):\s*<\/strong>\s*(<s>[^<]*<\/s>\s*)?\s*(?P<start>[^<\(]*)/', $page, $matches);
    foreach ($matches[0] as $i => $value) {
        $title = trim($matches['title'][$i]);
        $start = trim($matches['start'][$i]);
        $end = '';
        if (preg_match('/,?\s*(?P<year>[0-9]{4})/', $start, $match)) {
            $year = $match['year'];
            $start = str_replace($match[0], '', $start);
        } else {
            continue;
        }
        $duration = '';
        $time = NULL;
        if (preg_match('/(?P<start>[0-9]+:[0-9]+)(?:\s*-\s*(?P<end>[0-9]+:[0-9]+))?\s*/', $start, $match)) {
            $time = $match['start'];
            if (!empty($match['end'])) {
                $duration = (strtotime($match['end']) - strtotime($time)) / 60;
            }
            $start = str_replace($match[0], '', $start);
        }
        if (empty($duration)) {
            $sep = ' - ';
            $a = explode($sep, $start);
            $start = $a[0];
            if (count($a) > 1) {
                $end = $a[1] . ' ' . $year;
            } else {
                $duration = '00:00';
            }
        }
        $start = preg_replace('/-[0-9]+[a-z]+,/', ',', $start);
        $start = preg_replace('/,[^0-9]+$/', '', $start);
        if ($time) {
            $start .= ' ' . $time;
        }
        $start .= ' '. $year;
        $contests[] = array(
            'start_time' => $start,
            'end_time' => $end,
            'duration' => $duration,
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
