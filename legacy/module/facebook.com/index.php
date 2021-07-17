<?php
    require_once dirname(__FILE__) . "/../../config.php";

    function get_ids($page) {
        preg_match_all('#<link[^>]*href="(?P<href>[^"]*rsrc[^"]*)"[^>]*>#', $page, $matches);
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
        }
        return $ids;
    }

    curl_setopt($CID, CURLOPT_USERAGENT, 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36');

    unset($year);
    for (;;) {
        $url = $URL;
        if (isset($year)) {
            $url .= $year;
        }
        if (DEBUG) {
            echo "url = $url\n";
        }
        $page = curlexec($url);

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
        $data = curlexec($url, $params, array("json_output" => 1));

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
            $year = $node['contest_season']['season_vanity'];
            $url = rtrim($URL, '/') . "/$year/${node['contest_vanity']}";
            $scoreboard_url = rtrim($url) . '/scoreboard';
            $scoreboard_page = curlexec($scoreboard_url);
            $node['scoreboard_ids'] = get_ids($scoreboard_page);
            $contests[] = array(
                'start_time' => $node['start_time'],
                'duration' => $node['duration_in_seconds'] / 60,
                'title' => $node['name'] . ' ' . $year,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $node['id'],
                'standings_url' => $scoreboard_url,
                'info' => array('parse' => $node),
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
