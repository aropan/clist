<?php
    require_once dirname(__FILE__) . "/../../config.php";

    function parse_from_calendar() {
        global $URL, $HOST, $RID, $contests;

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
    }

    function parse_from_json() {
        global $URL, $HOST, $RID, $contests;

        $url_scheme_host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);
        curlexec($url_scheme_host);

        $times = array('present', 'future', 'past');

        foreach ($times as $time) {
            $offset = 0;
            $limit = 20;
            do {
                $url = "/api/list/contests/$time?sort_by=END&sorting_order=desc&offset=$offset";
                $data = curlexec($url, NULL, array("json_output" => 1));
                foreach ($data['contests'] as $c) {
                    $contests[] = array(
                        'start_time' => $c['contest_start_date_iso'],
                        'end_time' => $c['contest_end_date_iso'],
                        'title' => $c['contest_name'],
                        'url' => $url_scheme_host . $c['contest_code'],
                        'host' => $HOST,
                        'rid' => $RID,
                        'timezone' => 'UTC',
                        'key' => $c['contest_code'],
                    );
                }
                $offset += $limit;
            } while (count($data['contests']) == $limit && ($time != 'past' || isset($_GET['parse_full_list'])));
        }
    }

    parse_from_calendar();
    parse_from_json();

    if ($RID === -1) {
        print_r($contests);
    }
?>
