<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $parse_full_list = isset($_GET['parse_full_list']);

    $page = curlexec($URL);
    if (!preg_match('#XSRF-TOKEN=(?P<token>[^;]*)#', $page, $match)) {
        trigger_error("Not found xsrf token", E_USER_WARNING);
        return;
    }
    $token = $match['token'];

    $url = 'https://www.kaggle.com/api/i/competitions.CompetitionService/ListCompetitions';
    $params = array(
        'json_output' => true,
        'http_header' => array(
            'content-type: application/json',
            'x-xsrf-token: ' . $token,
        ),
    );
    $added = array();
    foreach (
        array(
            'LIST_OPTION_ACTIVE',
            'LIST_OPTION_DEFAULT',
            'LIST_OPTION_COMPLETED',
            'LIST_OPTION_DEFAULT',
        ) as $list_option
    ) {
        $page_token = '';
        do {
            $post = '{"selector":{"competitionIds":[],"listOption":"' . $list_option . '","sortOption":"SORT_OPTION_NEWEST","hostSegmentIdFilter":0,"searchQuery":"","prestigeFilter":"PRESTIGE_FILTER_UNSPECIFIED","participationFilter":"PARTICIPATION_FILTER_UNSPECIFIED","tagIds":[],"requireSimulations":false},"pageToken":"' . $page_token . '","pageSize":50,"readMask":"competitions"}';
            $data = curlexec($url, $post, $params);

            foreach ($data['competitions'] as $c) {
                $ok = true;
                foreach (array('id', 'title', 'competitionName', 'dateEnabled', 'deadline') as $f) {
                    if (!isset($c[$f])) {
                        trigger_error("Not found {$f} field", E_USER_WARNING);
                        $ok = false;
                        break;
                    }
                }
                if (!$ok || (isset($c['isPrivate']) && $c['isPrivate']) || isset($added[$c['id']])) {
                    continue;
                }
                $added[$c['id']] = true;

                $title = $c['title'];
                if (isset($c['categories']) && is_array($c['categories'])) {
                    $categories = array_map(function($cat) { return $cat['name']; }, $c['categories']);
                    $title .= ' [' . implode(', ', $categories) . ']';
                }

                $contests[] = array(
                    'start_time' => $c['dateEnabled'],
                    'end_time' => $c['deadline'],
                    'title' => $title,
                    'url' => url_merge($URL, $c['competitionName']),
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $c['id'],
                );
            }
            $page_token = isset($data['nextPageToken'])? $data['nextPageToken'] : false;
        } while ($page_token && $parse_full_list);
    }

    if ($RID === -1) {
        echo "Total contests: " . count($added) . "\n";
    }
?>
