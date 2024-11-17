<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $required_urls = array();

    function get_ids($page) {
        global $required_urls;
        preg_match_all('#<link[^>]*href="(?P<href>[^"]*rsrc[^"]*\.js\b[^"]*)"[^>]*>#', $page, $matches);
        $urls = $matches['href'];

        preg_match_all('#{"type":"js","src":"(?P<href>[^"]*rsrc[^"]*)"#', $page, $matches);
        foreach ($matches['href'] as $u) {
            $u = str_replace('\/', '/', $u);
            $urls[] = $u;
        }

        $urls = array_unique($urls);

        $urls_ = array_fill(0, count($urls), null);
        $offset = 0;
        foreach (array(true, false) as $state) {
            foreach ($urls as $url) {
                if ($state == isset($required_urls[$url])) {
                    $urls_[$offset++] = $url;
                }
            }
        }
        $urls = $urls_;

        $ids = array();
        $required_ids = array(
            "CodingCompetitionsContestSeasonRootQuery",
            "CodingCompetitionsContestSeriesRootQuery",
            "CodingCompetitionsContestScoreboardQuery",
            "CCEScoreboardQuery",
        );
        $required_ids = array_fill_keys($required_ids, true);

        foreach ($urls as $u) {
            $url = $u;
            $p = curlexec($u, null, array('no_logmsg' => true));
            $new_ids = array();
            if (preg_match_all('#{id:"(?P<id>[^"]*)"(?:[^{}]*(?:{[^}]*})?)*}#', $p, $matches, PREG_SET_ORDER)) {
                foreach ($matches as $match) {
                    if (preg_match('#,name:"(?P<name>[^"]*)"#', $match[0], $m)) {
                        $ids[$m['name']] = $match['id'];
                        $new_ids[] = $m['name'];
                    }
                }
            }
            if (preg_match_all('#__d\("(?P<name>[^_]*)_facebookRelayOperation"[^_]*exports="(?P<id>[^"]*)"#', $p, $matches, PREG_SET_ORDER)) {
                foreach ($matches as $match) {
                    $ids[$match['name']] = $match['id'];
                    $new_ids[] = $match['name'];
                }
            }

            foreach ($new_ids as $k) {
                if (isset($required_ids[$k])) {
                    unset($required_ids[$k]);
                }
            }
            if (empty($required_ids)) {
                break;
            }
        }
        return $ids;
    }

    $headers = json_decode(file_get_contents('sharedfiles/resource/facebook/headers.json'));
    $headers = array_map(function($k, $v) { return "$k: $v"; }, array_keys((array)$headers), (array)$headers);
    $cookie_file = 'sharedfiles/resource/facebook/cookies.txt';
    $curlexec_params = array('http_header' => $headers, 'with_curl' => true, 'cookie_file' => $cookie_file);

    unset($year);
    for (;;) {
        $url = $URL;
        if (isset($year)) {
            $url .= $year;
        }
        if (DEBUG) {
            echo "url = $url\n";
        }
        $page = curlexec($url, null, $curlexec_params);

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
            $url = rtrim($URL, '/') . "/$year/{$node['contest_vanity']}";
            $scoreboard_url = rtrim($url) . '/scoreboard';
            $url_ = $scoreboard_url;
            $scoreboard_page = curlexec($url_, NULL, ['with_curl' => true]);
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
?>
