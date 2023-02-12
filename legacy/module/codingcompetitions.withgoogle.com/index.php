<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $authorization = get_calendar_authorization();
    if (!$authorization) {
        trigger_error("Not get calendar credentials", E_USER_WARNING);
        return;
    }

    $js_urls = array();
    foreach (array(
        'https://codingcompetitions.withgoogle.com/codejam/schedule',
        'https://codingcompetitions.withgoogle.com/kickstart/schedule',
        'https://codingcompetitions.withgoogle.com/hashcode/schedule',
    ) as $url) {
        $page = curlexec($url);
        if (preg_match('/<script[^>]*src="(?<js>[^"]*static[^"]*main[^"]*js)"[^>]*>/', $page, $match)) {
            $js_urls[] = url_merge($url, $match['js']);
        }
    }
    $js_urls = array_unique($js_urls);
    if ($RID == -1) {
        print_r($js_urls);
    }

    $calendar_ids = array();
    $competitions = array();
    $missed_calendars = array();
    foreach ($js_urls as $url) {
        $page = curlexec($url);
        preg_match_all("/competition:[\"'](?P<name>[^\"']*)[\"'],([^,]*,)?competition_year:[\"'][0-9]{4}[\"'](,calendar_link:[\"'](?P<url>[^\"']*)[\"'])?/", $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $index => $match) {
            $competitions[$index + 1] = $match['name'];
            if (!isset($match['url'])) {
                $missed_calendars[] = $match['name'];
                continue;
            }
            $url = redirect_url($match['url']);
            if (preg_match('/cid=(?P<cid>[^&]+)/', urldecode($url), $m)) {
                $calendar_ids[] = base64_decode($m['cid']);
            }
        }

        if (isset($_GET['parse_full_list_2019'])) {
            preg_match_all("/{title:'(?P<title>[^']*)',([^{\[]*year:'(?!2019)[0-9]+'.*?)?rounds:(?P<rounds>\[{[^\]]*}\])}/s", $page, $matches, PREG_SET_ORDER);
            foreach ($matches as $match) {
                $title = $match['title'];
                $title = preg_replace('/[0-9]{4}/', '', $title);
                $title = preg_replace('/google/i', '', $title);
                $title = trim($title);
                $rounds = $match['rounds'];
                $rounds = strtr($rounds, "'", '"');
                $rounds = preg_replace('/([{,])([a-z]+):/', '\1"\2":', $rounds);
                $rounds = json_decode($rounds, true);
                foreach ($rounds as $r) {
                    if (!isset($r['scores']) || !isset($r['problems'])) {
                        continue;
                    }
                    if (isset($r['id'])) {
                        $key = $r['id'];
                        if (strlen($key) == 16) {
                            $u = strtolower(implode('', explode(' ', $title)));
                            $r['problems'] = "https://codingcompetitions.withgoogle.com/$u/round/$key";
                            $r['scores'] = "https://codingcompetitions.withgoogle.com/$u/round/$key";
                        }
                    } else {
                        preg_match('/[0-9]+[0-9a-z]*/', $r['scores'], $m);
                        $key = $m[0];
                    }

                    $t = $r['title'];
                    $t = preg_replace('/[0-9]{4}/', '', $t);
                    $t = preg_replace('/Distributed/i', '', $t);
                    foreach (explode(' ', $title) as $w) {
                        $t = preg_replace("#$w#i", '', $t);
                    }
                    $t = trim($t);
                    if (empty($t)) {
                        $t = $title;
                    } else {
                        $t = "$title. $t";
                    }

                    $contests[] = array(
                        'start_time' => $r['date'],
                        'duration' => $r['duration'],
                        'title' => $t,
                        'url' => $r['problems'],
                        'host' => $HOST,
                        'rid' => $RID,
                        'standings_url' => $r['scores'],
                        'timezone' => $TIMEZONE,
                        'key' => $key,
                    );
                }
            }
        }
    }

    $calendar_ids = array_unique($calendar_ids);
    if (DEBUG) {
        print_r($calendar_ids);
    }

    $normalize_title = function($title) {
        if (preg_match('#\b[0-9]{4}\b#', $title, $match)) {
            $year = $match[0];
            $title = str_replace($year, '', $title) . ' ' . $year;
        }
        $title = trim($title);
        $title = strtolower($title);
        $title = preg_replace('#\s+#', ' ', $title);
        return $title;
    };

    $url = 'https://codejam.googleapis.com/poll?p=e30';
    $page = curlexec($url, NULL, array('no_header' => true));
    $page = str_replace('_', '/', $page);
    $page = str_replace('-', '+', $page);
    $page = preg_replace('[^A-Za-z/+]', '', $page);
    $page_decode = base64_decode($page);
    $data = json_decode($page_decode, true, 512, JSON_INVALID_UTF8_IGNORE);
    $infos = array();
    foreach ($data['adventures'] as $adventure) {
        $competition = $competitions[$adventure['competition']];
        $competition = strtolower($competition);
        $competition = preg_replace('/\s+to\s+/', ' ', $competition);
        $competition = preg_replace('/[^a-z]/', '', $competition);
        foreach ($adventure['challenges'] as $challenge) {
            $key = $challenge['end_ms'] / 1000;
            $challenge['competition'] = $competition;

            $missed = false;
            foreach ($missed_calendars as $_ => $i) {
                if (strpos($adventure['title'], $i) !== false) {
                    $missed = true;
                    break;
                }
            }

            $title = strpos($challenge['title'], $adventure['title']) === false? $adventure['title'] . ' ' . $challenge['title'] : $challenge['title'];
            $title = $normalize_title($title);

            if ($missed) {
                $contests[] = array(
                    'start_time' => $challenge['start_ms'] / 1000,
                    'end_time' => $challenge['end_ms'] / 1000,
                    'title' => $challenge['title'],
                    'url' => "$URL{$challenge['competition']}/round/{$challenge['id']}",
                    'host' => "$HOST/{$challenge['competition']}",
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $challenge['id'],
                );
                continue;
            }

            $infos[$key] = $challenge;
            $infos[$title] = $challenge;
        }
    }

    foreach ($calendar_ids as $calendar_id) {
        $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar_id) . "/events?timeMin=" . urlencode(date('c', time() - 7 * 24 * 60 * 60));
        $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));
        if (!isset($data['items'])) {
            continue;
        }
        foreach ($data['items'] as $item) {
            if ($item['status'] != 'confirmed') {
                continue;
            }

            $date_key = isset($item['start']['dateTime'])? "dateTime" : "date";
            $normalized_title = $normalize_title($item['summary']);
            $title = trim(preg_replace('/\s*[0-9]{4}\s*/', ' ', $item['summary']));

            $skip_match_by_end = preg_match('/(registration|announce|practice.*session|\bhub\b.*open)/i', $title, $match);

            $timestamp = date("U", strtotime($item['end'][$date_key]));

            $start = $item['start'][$date_key];
            $end = $item['end'][$date_key];
            if (!$skip_match_by_end && isset($infos[$normalized_title])) {
                $info = $infos[$normalized_title];
                unset($infos[$normalized_title]);
                $url = "$URL{$info['competition']}/round/{$info['id']}";
                $host = "$HOST/{$info['competition']}";
                $start = $info['start_ms'] / 1000;
                $end = $info['end_ms'] / 1000;
            } else if (!$skip_match_by_end && isset($infos[$timestamp])) {
                $info = $infos[$timestamp];
                unset($infos[$timestamp]);
                $url = "$URL{$info['competition']}/round/{$info['id']}";
                $host = "$HOST/{$info['competition']}";
                $start = $info['start_ms'] / 1000;
                $end = $info['end_ms'] / 1000;
            } else {
                $url = $URL;
                $host = $HOST;
            }
            $contests[] = array(
                'start_time' => $start,
                'end_time' => $end,
                'title' => $title,
                'url' => $url,
                'host' => $host,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $item['id'],
                'delete_after_end' => boolval($skip_match_by_end),
            );
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }

    unset($normalize_title);
?>
