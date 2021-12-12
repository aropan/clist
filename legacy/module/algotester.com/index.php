<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $parse_full_list = isset($_GET['parse_full_list']);

    $url = 'https://algotester.com/en/Home/Events';
    $page = curlexec($url);

    preg_match_all('#<a[^>]*href="(?P<href>[^"]*/Contest/ViewScoreboard/(?P<id>[0-9]+))[^"]*"#', $page, $matches, PREG_SET_ORDER);
    $seen = array();
    $scoreboard_urls = array();
    foreach ($matches as $match) {
        if (isset($seen[$match['id']])) {
            continue;
        }
        $seen[$match['id']] = true;
        $scoreboard_urls[] = url_merge($url, $match['href']);
    }

    $seen = array();
    $tournament_ids = array();
    foreach ($scoreboard_urls as $scoreboard_url) {
        $page = curlexec($scoreboard_url);
        preg_match_all('#<a[^>]*href="(?P<href>[^"]*/Tournament/Display/(?P<id>[0-9]+))[^"]*"#', $page, $matches, PREG_SET_ORDER);

        foreach ($matches as $match) {
            if (isset($seen[$match['id']])) {
                continue;
            }
            $seen[$match['id']] = true;
            $tournament_ids[] = $match['id'];
        }
    }

    if ($parse_full_list) {
        $ids = range(1, 100500);
    } else {
        $ids = $tournament_ids;
    }

    $n_success = 0;
    foreach ($ids as $tournament_id) {
        if ($parse_full_list && 2 * $n_success < $tournament_id - 10) {
            break;
        }
        $offset = 0;
        $limit = 100;
        do {
            $tournament_url = "https://algotester.com/en/Contest/TournamentList/$tournament_id?actions=23&offset=$offset&limit=$limit";
            $data = curlexec($tournament_url, NULL, array("http_header" => array("X-Requested-With: XMLHttpRequest"), "json_output" => 1));
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
                    foreach ($c['Actions'] as $a) {
                        if ($a['Text'] == 'Scoreboard' && !empty($a['Url'])) {
                            $standings_url = url_merge($URL, $a['Url']);
                            if (empty($url)) {
                                $url = $standings_url;
                            }
                        }
                    }
                    $title = $c['Name']['Text'];
                    if (in_array($tournament_id, $tournament_ids)) {
                        $title .= ' [events]';
                    }
                    $contests[] = array(
                        'start_time' => $c['ContestStart'],
                        'end_time' => $c['ContestEnd'],
                        'title' => $title,
                        'url' => $url,
                        'standings_url' => $standings_url,
                        'host' => $HOST,
                        'rid' => $RID,
                        'timezone' => $TIMEZONE,
                        'key' => $c['Id'],
                    );
                }
            } else {
                trigger_error("Missing rows for tournament url = $tournament_url", E_USER_WARNING);
            }
            $total = $data['total'];
            $offset += $limit;
        } while ($parse_full_list && $offset < $total);
    }
?>
