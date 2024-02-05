<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*(Результаты|Ratings)\s*<#', $page, $match)) {
        return;
    }

    $base_url = $match['url'];
    $base_url = str_replace('&amp;', '&', $base_url);
    $n_skipped = 0;
    for ($iter = 0;; ++$iter) {
        if ($iter) {
            if (!isset($_GET['parse_full_list'])) {
                break;
            }
            $base_url = preg_replace_callback(
                '/([0-9]+)([ws])/',
                function ($match) {
                    return ($match[2] == 'w'? $match[1] - 1 . 's' : $match[1] . 'w');
                },
                $base_url,
            );
        }

        $url = $base_url;
        parse_str(parse_url($url, PHP_URL_QUERY), $query);

        $schedule = array();
        if (!isset($query['sbname'])) {
            break;
        }

        $camp = $query['sbname'];

        $schedule_url = "http://camp.icpc.petrsu.ru/{$camp}/schedule";
        if (DEBUG) {
            echo "schedule url = $schedule_url\n";
        }

        $page = curlexec($schedule_url);
        preg_match_all('#<b>(?P<date>[^<]*)</b>([^<]*</?(?:p|br)\s*/?>)*\s*(?:<span[^>]*>)?(?P<start_time>[0-9]+:[0-9]+)([-–\s]*(?P<end_time>[0-9]+:[0-9]+))?[-–\s]*(?:<a[^>]*>)?[^<]*(?:Contest|[A-Za-z\s]*\sRound|[A-Za-z\s]*\scontest)\s*(?:[0-9]+\s*[<(]|[^<]*</a>)#s', $page, $schedule, PREG_SET_ORDER);

        if (!preg_match('/[a-z]*(?P<year>[0-9]{4})[a-z]*/', $camp, $year)) {
            if ($iter) {
                break;
            }
            continue;
        }

        $year = $year['year'];

        foreach ($schedule as &$s) {
            $s['date'] = preg_replace('/\s*day\s*[0-9]+|\([^\)]*\)|,/', '', $s['date']);
            $s['date'] = trim($s['date'], ' ');
            $s['date'] .= ', ' . $year;
        }
        unset($s);

        if (parse_url($url, PHP_URL_HOST) == "") {
            $url = url_merge($URL, $url);
        }
        $camp_url = $url;
        $page = curlexec($camp_url);
        $page = str_replace('&nbsp;', ' ', $page);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>(?:\s*<[^/>]*(?:title="(?P<title>[^"]*)">)?)*\s*Day\s*(?P<day>0[0-9]+)\s*<#s', $page, $matches, PREG_SET_ORDER);

        if (empty($schedule) && empty($matches)) {
            $n_skipped += 1;
            if ($n_skipped > 3) {
                break;
            } else {
                continue;
            }
        }
        $n_skipped = 0;

        $days = array();
        $HOUR = 60 * 60;
        $DAY = 24 * $HOUR;
        foreach ($matches as $i => $values)
        {
            $url = $values['url'];
            $url = str_replace('&amp;', '&', $url);
            $page = curlexec($url);

            $data = array();
            $data['url'] = $url;
            if (!empty($values['title'])) {
                $data['title'] = $values['title'];
            }
            if (preg_match('#<h[23]>(?P<title>[^,]+)(?:,\s*(?P<date>[^<]*\b[0-9]+\b[^<]*))?</h[23]>#', $page, $match)) {
                if (!isset($data['title']) || preg_match('#Contest\s*[0-9]+#', $data['title'])) {
                    $data['title'] = $match['title'];
                }
                if (isset($match['date'])) {
                    $date = preg_replace('#^.*,\s*([^,]*,[^,]*)$#', '\1', $match['date']);
                    if (strtotime($date) !== false) {
                        $data['date'] = $date;
                    }
                }
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
            } else {
                $data['start_time'] = '10:00';
                if (empty($schedule) && !isset($data['date'])) {
                    $season = substr($camp, -1);
                    if ($season == 'w') {
                        $data['date'] = strftime('%B %d, %Y', strtotime("$year-02-27") + ($i - count($matches) + 1) * $DAY);
                    } else if ($season == 's') {
                        $data['date'] = strftime('%B %d, %Y', strtotime("$year-08-30") + ($i - count($matches) + 1) * $DAY);
                    }
                }
            }
            $days[intval($values['day'])] = $data;
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

        $camp_start_time = null;
        $camp_end_time = null;
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

            $key = $camp . '-day-' . $day;

            $start_time = isset($data['start_time'])? $date . ' ' . $data['start_time'] : $date;
            if (empty($camp_start_time)) {
                $camp_start_time = $start_time;
            }
            $camp_end_time = strtotime($start_time) + 2 * $DAY;

            $contests[] = array(
                'start_time' => $start_time,
                'end_time' => isset($data['end_time'])? $date . ' ' . $data['end_time'] : '',
                'duration' => isset($data['end_time'])? '' : (isset($data['start_time'])? '05:00' : '00:00'),
                'title' => $title,
                'url' => $url,
                'standings_url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $key,
            );
        }

        $contests[] = array(
            'start_time' => $camp_start_time,
            'end_time' => $camp_end_time,
            'title' => "Petrozavodsk Programming Camp $camp",
            'url' => $camp_url,
            'standings_url' => $camp_url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $camp,
            'info' => array('series' => 'ptzcamp'),
        );
    }
?>
