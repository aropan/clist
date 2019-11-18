<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://usaco.org/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $url = 'http://usaco.org/index.php?page=contests';
    $page = curlexec($url);

    preg_match_all('#<a[^>]*href="(?<url>[^"]*)"[^>]*>(?<name>[^<]*[0-9]{4}[^<]*Results)</a>#', $page, $matches, PREG_SET_ORDER);
    $results = array();
    foreach ($matches as $match) {
        $k = implode(' ', array_slice(explode(' ', $match['name']), 0, 3));
        $results[$k] = url_merge($url, $match['url']);
    }

    $page = curlexec($URL);

    if (!preg_match('#(\d{4})-(\d{4}) Schedule#', $page, $match)) return;
    list(, $start_year, $end_year) = $match;

    preg_match_all("#(?<start_time>[^\s]+\s\d+)-(?<end_time>(?:[^\s]+\s)?\d+):(?<title>[^<]*)#", $page, $matches, PREG_SET_ORDER);

    if (count($matches)) {
        $mindate = strtotime("{$matches[0]['start_time']}, $start_year");
    }

    foreach ($matches as $match)
    {
        $date = strtotime("{$match['start_time']}, $start_year");
        $year = $mindate <= $date? $start_year : $end_year;

        if (strpos($match['end_time'], ' ') === false) {
            list($month, ) = explode(' ', $match['start_time']);
            $match['end_time'] = $month . ' ' . $match['end_time'];
        }

        $start_time = "{$match['start_time']}, $year";
        $end_time = date('M j, Y', strtotime("{$match['end_time']}, $year") + 24 * 60 * 60);

        $title = trim($match['title']);

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
