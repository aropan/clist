<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://www.bubblecup.org/_api/competitionInfo';
    $data = curlexec($url, NULL, array('json_output' => true));

    if (!isset($data['rounds'])) {
        return;
    }

    foreach ($data['rounds'] as $round) {
        $desc = $round['description'];
        if (!preg_match(
            '#
                start\s+date\s+(?:<b[^>]*>)?(?P<start_time>[^<]*)(?:</b>)?.*?
                end\s+date\s+(?:<b[^>]*>)?(?P<end_time>[^<]*)
            #ix',
            $desc,
            $match,
        )) {
            continue;
        }

        $year = strftime('%Y', strtotime($match['start_time']));
        $month = intval(strftime('%m', strtotime($match['start_time'])));
        if ($month >= 9) {
            $year = $year + 1;
        }
        $title = preg_replace("#\s+#", " ", $round['name']);
        $key = ($year - 1) . "-" . $year . " " . $title;

        $contests[] = array(
            'start_time' => $match['start_time'],
            'end_time' => $match['end_time'],
            'title' => $title,
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $key
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
