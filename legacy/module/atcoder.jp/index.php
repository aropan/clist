<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $proxy_file = '/sharedfiles/resource/atcoder/proxy';
    $proxy = file_exists($proxy_file)? json_decode(file_get_contents($proxy_file)) : false;
    if ($proxy) {
        echo " (proxy)";
        curl_setopt($CID, CURLOPT_PROXY, $proxy->addr . ':' . $proxy->port);
    }

    $seen = array();
    foreach (array('?lang=en' => '', '?lang=ja' => '?lang=ja') as $query => $host) {
        $url = $URL . $query;

        $url_parsed = array();
        $n_contests = 0;

        do {
            $page = curlexec($url);
            $url_parsed[$url] = true;

            $regex = '#
                <tr[^>]*>(?:\s*<[^>]*>)+(?P<start_time>[^<]*)(?:<[^>]*>\s*)+
                (?:<span[^>]*title="(?P<rating_type>[^"]*)"[^>]*>[^<]*</span>\s*)?
                (?:<span[^>]*class="(?P<class>[^"]*)"[^>]*>[^<]*</span>\s*)?
                <a[^>]*href=[\"\'](?P<url>[^\"\']*/(?P<key>[^/]*))[\"\'][^>]*>(?P<title>[^<]*)(?:<[^>]*>\s*)+
                (?P<duration>[0-9]+(?::[0-9]+)+)
                </td>
            #x';

            preg_match_all($regex, $page, $matches, PREG_SET_ORDER);

            foreach ($matches as $c) {
                $k = $c['key'];
                if (isset($seen[$k])) {
                    continue;
                }
                $seen[$k] = true;
                $n_contests += 1;

                $title = $c['title'];

                $contest = array(
                    'start_time' => $c['start_time'],
                    'duration' => $c['duration'],
                    'title' => $title,
                    'url' => url_merge($URL, $c['url']),
                    'host' => $HOST . $host,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $k,
                );

                if (!empty($c['rating_type'])) {
                    $contest['kind'] = strtolower($c['rating_type']);
                }

                $contests[] = $contest;
            }

            $url = false;
            preg_match_all("#<a[^>]*href=[\"'](?P<url>[^\"']*/contests/archive(?:\?page=[0-9]+)?)[^>]*>#", $page, $matches);
            foreach ($matches['url'] as $u) {
                $u = url_merge($URL, $u);
                if (!isset($url_parsed[$u])) {
                    $url = $u;
                    break;
                }
            }
        } while (isset($_GET['parse_full_list']) && $url);

        if (!$n_contests) {
            break;
        }
    }

    $year = date('Y');

    $contest = array(
        'start_time' => '01 Jan ' . $year,
        'end_time' => '31 Dec ' . $year,
        'title' => "AtCoder Race Ranking $year. Heuristic",
        'key' => "atcoder-race-ranking-$year-heuristic",
        'url' => $URL,
        'info' => array('_inherit_stage' => true),
        'host' => $HOST,
        'timezone' => $TIMEZONE,
        'rid' => $RID,
    );
    $contests[] = $contest;

    $contest = array(
        'start_time' => '01 Jan ' . $year,
        'end_time' => '31 Dec ' . $year,
        'title' => "AtCoder Race Ranking $year. Algorithm",
        'key' => "atcoder-race-ranking-$year-algorithm",
        'url' => $URL,
        'info' => array('_inherit_stage' => true),
        'host' => $HOST,
        'timezone' => $TIMEZONE,
        'rid' => $RID,
    );
    $contests[] = $contest;

    if ($RID === -1) {
        print_r($contests);
    }

    if ($proxy) {
        curl_setopt($CID, CURLOPT_PROXY, null);
    }
?>
