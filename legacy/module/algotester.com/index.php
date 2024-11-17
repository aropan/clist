<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $parse_full_list = isset($_GET['parse_full_list']);

    $urls = array('https://algotester.com/en/Home/Events');

    $url = 'https://algotester.com/en';
    $page = curlexec($url);
    preg_match_all('#<a[^>]*href="(?P<href>/[^"/]*/?)"[^>]*>#', $page, $matches, PREG_SET_ORDER);
    foreach ($matches as $match) {
        if (preg_match('#/(en|uk|logo)/?#i', $match['href'])) {
            continue;
        }
        $urls[] = url_merge($url, $match['href']);
    }
    $urls = array_unique($urls);

    $scoreboard_urls = array('https://algotester.com/en');
    $seen = array();
    foreach ($urls as $url) {
        $page = curlexec($url);

        preg_match_all('#<a[^>]*href="(?P<href>[^"]*/Contest/(ViewScoreboard|Display)/(?P<id>[0-9]+))[^"]*"#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            if (isset($seen[$match['id']])) {
                continue;
            }
            $seen[$match['id']] = true;
            $scoreboard_urls[] = url_merge($url, $match['href']);
        }
    }

    $seen = array();
    $tournament_ids = array();
    $tournament_urls = array();
    foreach ($scoreboard_urls as $scoreboard_url) {
        $page = curlexec($scoreboard_url, null, array('no_logmsg' => true));
        preg_match('#<title>(?P<title>[^<]*)</title>#', $page, $match);

        preg_match_all('#<a[^>]*href="(?P<href>[^"]*/Tournament/Display/(?P<id>[0-9]+))[^"]*"#', $page, $matches, PREG_SET_ORDER);

        foreach ($matches as $match) {
            if (isset($seen[$match['id']])) {
                continue;
            }
            $seen[$match['id']] = true;
            $tournament_ids[] = $match['id'];
        }

        preg_match_all('#<li>\s*<a[^>]*href="(?P<href>/?[^"/]+)"[^>]*>[^<]*</a>\s*</li>#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            $url = url_merge($scoreboard_url, $match['href']);
            if (in_array($url, $tournament_urls)) {
                continue;
            }
            $tournament_urls[] = $url;
        }
    }

    foreach ($tournament_urls as $tournament_url) {
        $page = curlexec($tournament_url, null, array('no_logmsg' => true));
        preg_match_all('#/TournamentList/(?P<id>[0-9]+)#', $page, $matches, PREG_SET_ORDER);

        foreach ($matches as $match) {
            if (isset($seen[$match['id']])) {
                continue;
            }
            $seen[$match['id']] = true;
            $tournament_ids[] = $match['id'];
        }
    }

    if (empty($tournament_ids)) {
        trigger_error("Missing tournament ids", E_USER_WARNING);
        return;
    }

    $seen = array();
    $ids = array_merge($tournament_ids, range(1, 100500));
    $n_success = 0;
    foreach ($ids as $tournament_id) {
        if (isset($seen[$tournament_id])) {
            continue;
        }
        $seen[$tournament_id] = true;

        $in_tournament = in_array($tournament_id, $tournament_ids);
        if (!$in_tournament && 1.1 * $n_success < $tournament_id - 10) {
            break;
        }

        $offset = 0;
        $limit = 100;
        do {
            $tournament_url = "https://algotester.com/en/Contest/TournamentList/$tournament_id?actions=23&offset=$offset&limit=$limit";
            $data = curlexec($tournament_url, NULL, array("no_logmsg" => true, "http_header" => array("X-Requested-With: XMLHttpRequest"), "json_output" => 1));
            if (!isset($data['total'])) {
                break;
            }
            if (isset($data['rows'])) {
                $n_success += 1;
                foreach ($data['rows'] as $c) {
                    $url = $c['Name']['Url'];
                    if (!empty($url)) {
                        $url = url_merge($URL, $url);
                    }
                    $standings_url = false;
                    foreach ($c['Actions'] as $a) {
                        if ($a['Text'] == 'Scoreboard' && !empty($a['Url'])) {
                            $standings_url = url_merge($URL, $a['Url']);
                            if (empty($url)) {
                                $url = $standings_url;
                            }
                            break;
                        }
                    }
                    if (empty($url)) {
                        $url = "https://algotester.com/en/Tournament/Display/$tournament_id";
                    }
                    if (empty($standings_url)) {
                        $standings_url = 'https://algotester.com/en/Contest/ViewScoreboard/'. $c['Id'];
                    }
                    $title = $c['Name']['Text'];

                    $contest = array(
                        'start_time' => $c['ContestStart'],
                        'end_time' => $c['ContestEnd'],
                        'title' => $title,
                        'url' => $url,
                        'host' => $HOST,
                        'rid' => $RID,
                        'timezone' => $TIMEZONE,
                        'key' => $c['Id'],
                        'invisible' => $in_tournament? "false" : "true",
                        'standings_url' => $standings_url,
                    );
                    $contests[] = $contest;
                }
            } else {
                trigger_error("Missing rows for tournament url = $tournament_url", E_USER_WARNING);
            }
            $total = $data['total'];
            $offset += $limit;
        } while ($parse_full_list && $offset < $total);
    }
?>
