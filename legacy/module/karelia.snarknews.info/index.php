<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://karelia.snarknews.info/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Результаты\s*<#', $page, $match)) {
        return;
    }

    $url = $match['url'];
    //if (1) {
        //$urls = array(
            //preg_replace('/([0-9])[ws]/', '\1s', $url),
            //preg_replace('/([0-9])[ws]/', '\1w', $url)
        //);
    //} else {
    $urls = array($url);
    //}

    foreach ($urls as $url) {
        parse_str(parse_url($url, PHP_URL_QUERY), $query);

        $schedule = array();
        if (isset($query['sbname'])) {
            $schedule_url = "http://camp.acm.petrsu.ru/{$query['sbname']}/schedule";
            if ($RID == -1) {
                echo "schedule url = $schedule_url\n";
            }
            $page = curlexec($schedule_url);
            preg_match_all('#<b>(?P<date>[^<]*)</b>([^<]*<(?:p|br)\s*/?>)*\s*(?:<span[^>]*>)?(?P<start_time>[0-9]+:[0-9]+)(\s*[-–]\s*(?P<end_time>[0-9]+:[0-9]+))?\s*[-–]\s*(?:<a[^>]*>)?[^<]*(?:Contest|[A-Za-z\s]*\sRound|[A-Za-z\s]*\scontest)\s*[0-9]+\s*[<\(]#s', $page, $schedule, PREG_SET_ORDER);

            if (!count($schedule)) {
                return;
            }

            if (!preg_match('/[a-z]*[0-9]{4}[a-z]*/', $query['sbname'], $year)) {
                return;
            }
            $year = $year[0];

            foreach ($schedule as &$s) {
                $s['date'] = preg_replace('/\s*day\s*[0-9]+|\([^\)]*\)|,/', '', $s['date']);
                $s['date'] = trim($s['date'], ' ');
                $s['date'] .= ', ' . $year;
            }
            unset($s);
        }
        if (parse_url($url, PHP_URL_HOST) == "") {
            $url = 'http://' . parse_url($URL, PHP_URL_HOST) . "/" . $url;
        }
        $page = curlexec($url);
        $page = str_replace('&nbsp;', ' ', $page);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>(?:\s*<[^/>]*(?:title="(?P<title>[^"]*)">)?)*\s*Day\s*(?P<day>0[0-9]+)\s*<#s', $page, $matches);

        unset($prev_date);

        $days = array();
        foreach ($matches[0] as $i => $value)
        {
            $url = $matches['url'][$i];
            $page = curlexec($url);
            $data = array();
            $data['url'] = $url;
            if (preg_match('#<h2>(?P<title>[^,]*)(?:, (?P<date>[0-9]+\s+[^<]*))?</h2>#', $page, $match)) {
                $data['title'] = $match['title'];
                if (isset($match['date'])) {
                    $data['date'] = preg_replace('#^.*,\s*([^,]*,[^,]*)$#', '\1', $match['date']);
                }
            } else if (isset($matches['title'][$i])) {
                $data['title'] = $matches['title'][$i];
            } else {
                continue;
            }

            if ($i < count($schedule)) {
                $s = $schedule[$i];
                if (!isset($data['date'])) {
                    $data['date'] = strftime('%B %d, %Y', strtotime($s['date']));
                }
                $data['start_time'] = $s['start_time'];
                if (isset($s['end_time'])) {
                    $data['end_time'] = $s['end_time'];
                }
            }

            $days[intval($matches['day'][$i])] = $data;
        }
        foreach ($days as $day => $data) {
            if (!isset($data['date']) && isset($days[$day - 1]) && isset($days[$day - 1]['date'])) {
                $days[$day]['date'] = strftime('%B %d, %Y', strtotime($days[$day - 1]['date']) + 24 * 60 * 60);
            }
        }
        foreach (array_reverse($days, true) as $day => $data) {
            if (!isset($data['date']) && isset($days[$day + 1]) && isset($days[$day + 1]['date'])) {
                $days[$day]['date'] = strftime('%B %d, %Y', strtotime($days[$day + 1]['date']) - 24 * 60 * 60);
            }
        }

        foreach ($days as $day => $data) {
            if (!isset($data['date'])) {
                continue;
            }
            $title = $data['title'];
            $date = $data['date'];
            $url = $data['url'];
            $prefix = 'Day ' . $day . ': ';
            if (substr($title, 0, strlen($prefix)) != $prefix) {
                $title = $prefix . $title;
            }

            if ($RID == -1) {
                echo $title . ' | ' . $date . "\n";
            }

            $contests[] = array(
                'start_time' => isset($data['start_time'])? $date . ' ' . $data['start_time'] : $date,
                'end_time' => isset($data['end_time'])? $date . ' ' . $data['end_time'] : '',
                'duration' => isset($data['end_time'])? '' : (isset($data['start_time'])? '05:00' : '00:00'),
                'title' => $title,
                'url' => $url,
                'standings_url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $date,
            );
        }
    }
?>
