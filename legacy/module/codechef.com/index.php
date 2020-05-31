<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $authorization = get_calendar_authorization();
    if (!$authorization) {
        return;
    }

    $calendar = "codechef.com_3ilksfmv45aqr3at9ckm95td5g@group.calendar.google.com";
    $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar) . "/events?timeMin=" . urlencode(date('c', time() - 24 * 60 * 60));
    $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));

    if (!isset($data["items"])) {
        print_r($data);
        return;
    }

    foreach ($data["items"] as $item)
    {
        if ($item['status'] != 'confirmed') {
            continue;
        }

        if (!isset($item['location'])) {
            continue;
        }
        $url = $item['location'];

        $url = (!empty($url) && parse_url($url, PHP_URL_SCHEME) == "")? "http://$url" : $url;

        if (empty($url) || $url == "http://$HOST") {
            continue;
        }

        if (!preg_match('#/(?<key>[A-Za-z0-9_ ]+)/?$#', $url, $match)) {
            continue;
        }
        $key = $match['key'];
        if (!preg_match('#^(?<pref>[A-Za-z0-9_ \.:\/]+?)[A-Za-z0-9_ ]+$#', $url, $match)) {
            continue;
        }
        $url = $match['pref'] . $key;

        $date_key = isset($item['start']['dateTime'])? "dateTime" : "date";

        $contests[] = array(
            'start_time' => $item['start'][$date_key],
            'end_time' => $item['end'][$date_key],
            'title' => $item['summary'],
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => 'UTC',
            'key' => $key
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
