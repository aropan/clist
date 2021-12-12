<?php
    require_once dirname(__FILE__) . "/../../config.php";

    function get_ids($page) {
        preg_match_all('#<link[^>]*href="(?P<href>[^"]*rsrc[^"]*\.js\b[^"]*)"[^>]*>#', $page, $matches);
        $urls = $matches['href'];
        // preg_match_all('#{"type":"js","src":"(?P<href>[^"]*rsrc[^"]*)"#', $page, $matches);
        // foreach ($matches['href'] as $u) {
        //     $u = str_replace('\/', '/', $u);
        //     $urls[] = $u;
        // }
        // $urls = array_unique($urls);

        $ids = array();
        foreach ($urls as $u) {
            if (DEBUG) {
                echo "get id url = $u\n";
            }
            $p = curlexec($u);
            if (preg_match_all('#{id:"(?P<id>[^"]*)"(?:[^{}]*(?:{[^}]*})?)*}#', $p, $matches, PREG_SET_ORDER)) {
                foreach ($matches as $match) {
                    if (preg_match('#,name:"(?P<name>[^"]*)"#', $match[0], $m)) {
                        $ids[$m['name']] = $match['id'];
                    }
                }
            }
            if (preg_match_all('#__d\("(?P<name>[^_]*)_facebookRelayOperation"[^_]*exports="(?P<id>[^"]*)"#', $p, $matches, PREG_SET_ORDER)) {
                foreach ($matches as $match) {
                    $ids[$match['name']] = $match['id'];
                }
            }
        }
        return $ids;
    }

    $url = "https://www.facebook.com/";
    $page = curlexec($url);

    if (preg_match('#<form[^>]*action="(?P<url>[^"]*/login/[^"]*)"#', $page, $match)) {
        $url = $match['url'];
        preg_match_all('#<input[^>]*name="(?P<name>[^"]*)"[^>]*value="(?P<value>[^"]*)"#', $page, $matches, PREG_SET_ORDER);
        $data = array();
        foreach ($matches as $match) {
            $data[$match['name']] = $match['value'];
        }
        require_once dirname(__FILE__) . "/secret.php";
        $data['email'] = $FACEBOOK_USERNAME;
        $data['pass'] = $FACEBOOK_PASSWORD;
        unset($FACEBOOK_EMAIL);
        unset($FACEBOOK_USERNAME);
        unset($FACEBOOK_PASSWORD);
        $page = curlexec($url, $data);
    }

    $headers = array(
        'pragma: no-cache',
        'cache-control: no-cache',
        'upgrade-insecure-requests: 1',
        'sec-fetch-site: same-origin',
        'sec-fetch-mode: navigate',
        'sec-fetch-user: ?1',
        'sec-fetch-dest: document',
    );

    unset($year);
    for (;;) {
        $url = $URL;
        if (isset($year)) {
            $url .= $year;
        }
        if (DEBUG) {
            echo "url = $url\n";
        }
        $page = curlexec($url, null, array("http_header" => $headers));

        unset($fb_dtsg);
        if (preg_match('#\["DTSGInitialData",\[\],{"token":"(?P<token>[^"]*)"#', $page, $match)) {
            $fb_dtsg = $match['token'];
        }

        preg_match('#\["LSD",\[\],{"token":"(?P<token>[^"]*)"#', $page, $match);
        $lsd_token = $match['token'];
        if (DEBUG) {
            echo "LDS = $lsd_token\n";
        }

        $ids = get_ids($page);
        if (!isset($ids['CodingCompetitionsContestSeasonRootQuery'])) {
            break;
        }

        $url = 'https://www.facebook.com/api/graphql/';
        if (isset($year)) {
            $params = array(
                "lsd" => $lsd_token,
                "fb_api_caller_class" => "RelayModern",
                "fb_api_req_friendly_name" => "CodingCompetitionsContestSeasonRootQuery",
                "variables" => '{"series_vanity":"hacker-cup","season_vanity":"' . $year . '"}',
                "doc_id" => $ids['CodingCompetitionsContestSeasonRootQuery'],
            );
        } else {
            $params = array(
                "lsd" => $lsd_token,
                "fb_api_caller_class" => "RelayModern",
                "fb_api_req_friendly_name" => "CodingCompetitionsContestSeriesRootQuery",
                "variables" => '{"series_vanity":"hacker-cup"}',
                "doc_id" => $ids['CodingCompetitionsContestSeriesRootQuery'],
            );
        }
        if (isset($fb_dtsg)) {
            $params['fb_dtsg'] = $fb_dtsg;
        }
        $data = curlexec($url, $params, array("json_output" => 1));
        if (!is_array($data)) {
            trigger_error("Wrong response data", E_USER_WARNING);
            return;
        }
        if (isset($data['errors'])) {
            $errors = array();
            foreach ($data['errors'] as $_ => $e) {
                $errors[] = $e['message'];
            }
            $error = implode('; ', $errors);
            trigger_error("Error on get response = $error", E_USER_WARNING);
            return;
        }

        $contest_series = $data['data']['contestSeries'];
        if (isset($contest_series['latest_season'])) {
            $season = $contest_series['latest_season']['nodes'][0];
        } else {
            $season = $contest_series['contestSeason'];
        }

        if (empty($season)) {
            break;
        }

        foreach ($season['season_contests']['nodes'] as $node) {
            $info = array('parse' => $node);
            $year = $node['contest_season']['season_vanity'];
            $url = rtrim($URL, '/') . "/$year/${node['contest_vanity']}";
            $scoreboard_url = rtrim($url) . '/scoreboard';
            $scoreboard_page = curlexec($scoreboard_url);
            $scoreboard_ids = get_ids($scoreboard_page);
            if ($scoreboard_ids) {
                $info['_scoreboard_ids'] = $scoreboard_ids;
            }

            if (isset($node['duration_in_seconds'])) {
                $duration = $node['duration_in_seconds'] / 60;
            } else if (isset($node['duration_text']) && preg_match('#^(?P<hours>[0-9]+)\s+hours$#', $node['duration_text'], $match)) {
                $duration = $match['hours'] * 60;
            } else {
                $duration = '00:00';
            }
            $contests[] = array(
                'start_time' => $node['start_time'],
                'duration' => $duration,
                'title' => $node['name'] . ' ' . $year,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $node['id'],
                'standings_url' => $scoreboard_url,
                'info' => $info,
            );
        }

        if (!isset($_GET['parse_full_list'])) {
            break;
        }
        --$year;
    }

    if (DEBUG) {
        print_r($contests);
    }

    curl_setopt($CID, CURLOPT_USERAGENT, $USER_AGENT);
?>
