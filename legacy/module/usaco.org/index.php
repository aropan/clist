<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = 'http://usaco.org/index.php?page=contests';
    $curl_params = ['with_curl' => true, 'curl_args_file' => '/sharedfiles/resource/usaco/curl.args'];
    $page = curlexec($url, NULL, $curl_params);

    $results = array();
    preg_match_all('#<a[^>]*href="(?<url>[^"]*result[^"]*)"[^>]*>[^<]*(?<name>[0-9]{4}[^<]*Results)</a>#', $page, $matches, PREG_SET_ORDER);
    foreach ($matches as $match) {
        $k = implode(' ', array_slice(explode(' ', $match['name']), 0, 3));
        $results[strtolower($k)] = url_merge($url, $match['url']);
    }
    preg_match_all('#<p>[^<]*(?<name>[0-9]{4}[^<]*)<a[^>]*href="(?<url>[^"]*result[^"]*)"[^>]*>here</a>#', $page, $matches, PREG_SET_ORDER);
    foreach ($matches as $match) {
        $k = implode(' ', array_slice(explode(' ', $match['name']), 0, 3));
        $results[strtolower($k)] = url_merge($url, $match['url']);
    }

    $page = curlexec($URL, NULL, $curl_params);

    if (!preg_match('#>\s*(\d{4})-(\d{4})[^<]*Schedule#', $page, $match)) return;
    list(, $start_year, $end_year) = $match;

    preg_match_all("#(?<start_time>[^\s]+\s\d+)-(?<end_time>(?:[^\s]+\s)?\d+):(?<title>[^<]*)#", $page, $matches, PREG_SET_ORDER);

    if (count($matches)) {
        $mindate = strtotime("{$matches[0]['start_time']}, $start_year");
    }

    foreach ($matches as $match)
    {
        $title = trim($match['title']);
        if (preg_match('#\bioi\b|\btraining\b.*\bcamp\b#i', $title)) {
            continue;
        }

        $date = strtotime("{$match['start_time']}, $start_year");
        $year = $mindate <= $date? $start_year : $end_year;

        if (strpos($match['end_time'], ' ') === false) {
            list($month, ) = explode(' ', $match['start_time']);
            $match['end_time'] = $month . ' ' . $match['end_time'];
        }

        $start_time = "{$match['start_time']}, $year";
        $end_time = date('M j, Y', strtotime("{$match['end_time']}, $year") + 24 * 60 * 60);

        $c = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'duration_in_secs' => 4 * 60 * 60,
            'title' => $title,
            'host' => $HOST,
            'url' => $URL,
            'timezone' => $TIMEZONE,
            'key' => $title . " " . $year,
            'rid' => $RID
        );

        $keys = array(
            date('Y F', strtotime($start_time)) . ' Contest',
            date('Y', strtotime($start_time)) . ' ' . $title,
        );
        foreach ($keys as $k) {
            $k = strtolower($k);
            if (isset($results[$k])) {
                $c['standings_url'] = $results[$k];
                unset($results[$k]);
                break;
            }
        }

        $contests[] = $c;
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
