<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $prefix_contest = parse_url($URL, PHP_URL_SCHEME) . '://' . parse_url($URL, PHP_URL_HOST) . '/contests/';

    $http_header = array('http_header' => array('content-type: application/json'), 'json_output' => true);

    $datas = array();

    $url = 'https://www.codingame.com/services/Challenge/findXNextVisibleChallenges';
    $data = curlexec($url, '[2]', $http_header);
    if (!is_array($data)) {
        trigger_error("data = $data from $url", E_USER_WARNING);
        return;
    }
    $datas = array_merge($datas, $data);

    $url = 'https://www.codingame.com/services/Challenge/findPastChallenges';
    $data = curlexec($url, '[null]', $http_header);
    if (!is_array($data)) {
        trigger_error("data = $data from $url", E_USER_WARNING);
        return;
    }
    $datas = array_merge($datas, array_slice($data, 0, 3));

    $pids = array();
    foreach ($datas as $a) {
        if (isset($a['publicId'])) {
            $pids[] = $a['publicId'];
        }
    }

    $url = 'https://forum.codingame.com/t/clash-wars-mini-clash-of-code-tournament/145336';
    $n_page = 0;
    for (;;) {
        $page = curlexec($url);

        preg_match_all('#href="[^"]*codingame.com/hackathon/(?P<id>[^/"]*)"#', $page, $matches);
        $pids = array_merge($pids, array_slice($matches['id'], -3));

        if (!preg_match_all('#<a[^>]*rel="next"[^>]*href="(?P<href>[^"]*page=(?P<page>[0-9]+))"#', $page, $matches, PREG_SET_ORDER)) {
            break;
        }
        $match = end($matches);
        $match_page = intval($match['page']);
        if ($match_page < $n_page) {
            break;
        }
        $n_page = $match_page;
        $url = $match['href'];
    }

    $pids = array_unique($pids);

    foreach ($pids as $pid) {
        $u = 'https://www.codingame.com/services/ChallengeRemoteService/findWorldCupByPublicId';
        $j = curlexec($u, $postfields='["' . $pid . '", null]', $http_header);
        if (!isset($j['challenge'])) {
            continue;
        }
        $data = $j['challenge'];
        $ok = true;
        foreach (array('date', 'publicId', 'title') as $key) {
            if (!isset($data[$key]) || empty($data[$key])) {
                $ok = false;
                break;
            }
        }
        if (!$ok) {
            continue;
        }

        $duration = NULL;
        if (isset($data['descriptionJson'])) {
            $description = json_decode($data['descriptionJson'], true);
            if (isset($description['challengeOptions'])) {
                foreach ($description['challengeOptions'] as $options) {
                    if ($options['iconId'] == 1) {
                        $duration = preg_replace('/<[^>]*>/', '', $options['title']);
                        break;
                    }
                }
            }
        }
        if (!isset($duration)) {
            if (isset($data['lateTimeMax']) && $data['lateTimeMax']) {
                $duration = $data['lateTimeMax'] / 60.0;
            } else {
                $duration = '00:00';
            }
        } else if (strpos($duration, ' -> ')) {
            list($start, $end) = explode(' -> ', $duration);
            if (strpos($start, "  ")) {
                list($_, $start) = explode('  ', $start);
            }
            $start = strtotime(preg_replace('#[A-Z]{3}#', '', $start));
            $end = strtotime(preg_replace('#[A-Z]{3}#', '', $end));
            $duration = ($end - $start) / 60;
        }

        $contests[] = array(
            'start_time' => $data['date'] / 1000,
            'duration' => $duration,
            'title' => $data['title'],
            'url' => $prefix_contest . $data['publicId'],
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $data['publicId']
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
