<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*(Результаты|Ratings)\s*<#', $page, $match)) {
        return;
    }

    $base_url = $match['url'];
    for ($iter = 0; ; ++$iter) {
        if ($iter) {
            if (!isset($_GET['parse_full_list'])) {
                break;
            }
            $base_url = preg_replace_callback(
                '/([0-9]+)([ws])/',
                function ($match) {
                    return ($match[2] == 'w'? $match[1] - 1 . 's' : $match[1] . 'w');
                },
                $url,
            );
        }

        $url = $base_url;
        parse_str(parse_url($url, PHP_URL_QUERY), $query);

        $schedule = array();
        if (!isset($query['sbname'])) {
            break;
        }

        $schedule_url = "http://camp.icpc.petrsu.ru/{$query['sbname']}/schedule";
        if (DEBUG) {
            echo "schedule url = $schedule_url\n";
        }

        $page = curlexec($schedule_url);
        preg_match_all('#<b>(?P<date>[^<]*)</b>([^<]*</?(?:p|br)\s*/?>)*\s*(?:<span[^>]*>)?(?P<start_time>[0-9]+:[0-9]+)([-–\s]*(?P<end_time>[0-9]+:[0-9]+))?[-–\s]*(?:<a[^>]*>)?[^<]*(?:Contest|[A-Za-z\s]*\sRound|[A-Za-z\s]*\scontest)\s*(?:[0-9]+\s*[<(]|[^<]*</a>)#s', $page, $schedule, PREG_SET_ORDER);

        if (!count($schedule) || !preg_match('/[a-z]*[0-9]{4}[a-z]*/', $query['sbname'], $year)) {
            if ($iter) {
                break;
            }
            continue;
        }

        $year = $year[0];

        foreach ($schedule as &$s) {
            $s['date'] = preg_replace('/\s*day\s*[0-9]+|\([^\)]*\)|,/', '', $s['date']);
            $s['date'] = trim($s['date'], ' ');
            $s['date'] .= ', ' . $year;
        }
        unset($s);

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
            if (isset($matches['title'][$i])) {
                $data['title'] = $matches['title'][$i];
            }
            if (preg_match('#<h2>(?P<title>[^,]*)(?:, (?P<date>[0-9]+\s+[^<]*))?</h2>#', $page, $match)) {
                if (!isset($data['title'])) {
                    $data['title'] = $match['title'];
                }
                if (isset($match['date'])) {
                    $data['date'] = preg_replace('#^.*,\s*([^,]*,[^,]*)$#', '\1', $match['date']);
                }
            }
            if (!isset($data['title'])) {
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

            if (DEBUG) {
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
