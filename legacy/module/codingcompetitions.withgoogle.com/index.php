<?php
    require_once dirname(__FILE__) . '/../../config.php';

    if (!isset($URL)) $URL = 'https://codingcompetitions.withgoogle.com';
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $authorization = get_calendar_authorization();
    if (!$authorization) {
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

    $calendar_ids = array();
    $competitions = array();
    foreach ($js_urls as $url) {
        $page = curlexec($url);
        preg_match_all("/competition:'(?P<name>[^']*)',([^,]*,)?competition_year:'[0-9]{4}'(,calendar_link:'(?P<url>[^']*)')?/", $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $index => $match) {
            $competitions[$index + 1] = $match['name'];
            if (!isset($match['url'])) {
                continue;
            }
            $url = redirect_url($match['url']);
            if (preg_match('/cid=(?P<cid>[^&]+)/', urldecode($url), $m)) {
                $calendar_ids[] = base64_decode($m['cid']);
            }
        }
    }
    $calendar_ids = array_unique($calendar_ids);

    $url = 'https://codejam.googleapis.com/poll?p=e30';
    $page = curlexec($url, NULL, array('no_header' => true));
    $page_decode = base64_decode($page);
    $data = json_decode($page_decode, true);
    $infos = array();
    foreach ($data['adventures'] as $adventure) {
        $competition = $competitions[$adventure['competition']];
        foreach ($adventure['challenges'] as $challenge) {
            $key = $challenge['start_ms'] / 1000;
            $challenge['competition'] = preg_replace('/[^a-z]/', '', strtolower($competition));
            $infos[$key] = $challenge;
        }
    }

    foreach ($calendar_ids as $calendar_id) {
        $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar_id) . "/events?timeMin=" . urlencode(date('c', time() - 3 * 24 * 60 * 60));
        $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));
        if (!isset($data['items'])) {
            continue;
        }
        foreach ($data['items'] as $item) {
            if ($item['status'] != 'confirmed') {
                continue;
            }

            $date_key = isset($item['start']['dateTime'])? "dateTime" : "date";
            $title = trim(preg_replace('/\s*[0-9]{4}\s*/', ' ', $item['summary']));

            $timestamp = date("U", strtotime($item['start'][$date_key]));
            if (isset($infos[$timestamp])) {
                $url = "$URL{$infos[$timestamp]['competition']}/round/{$infos[$timestamp]['id']}";
                unset($infos[$timestamp]);
            } else {
                $url = $URL;
            }
            $contests[] = array(
                'start_time' => $item['start'][$date_key],
                'end_time' => $item['end'][$date_key],
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $item['id'],
            );
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
