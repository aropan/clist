<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://neerc.ifmo.ru/archive/index.html";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);

    preg_match_all('#<a[^>]*class="menuleft"[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]+</a>#', $page, $matches, PREG_SET_ORDER);
    $urls = array();
    foreach ($matches as $match) {
        $urls[] = url_merge($URL, $match['url']);

        if (!isset($_GET['parse_full_list'])) {
            break;
        }
    }

    foreach ($urls as $url) {
        preg_match('#(?P<year>[0-9]{4})#', $url, $match);
        $year = $match['year'];

        $page = curlexec($url);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*[0-9]+[^"]*standings[^"]*)"[^>]*>\s*Standings\s*</a>#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            $u = url_merge($url, $match['url']);
            $page = curlexec($u);

            preg_match('#<h2[^>]*>(?P<title>[^<]*)</h2>#', $page, $m);
            $title = $m['title'];
            if (empty($title)) {
                $a = explode('/', $u);
                $a = array_slice($a, 4, count($a) - 5);
                $title = implode(' ', array_reverse($a));
                $title = ucwords($title);
            }
            $key = preg_replace('/[^- a-zA-Z0-9]/', '', $title);
            $key = preg_replace('/[- ]+/', ' ', $key);
            $key = strtolower($key);

            $contests[] = array(
                'start_time' => "$year-09-02",
                'duration' => '05:00',
                'title' => $title,
                'host' => $HOST,
                'url' => $u,
                'standings_url' => $u,
                'timezone' => $TIMEZONE,
                'key' => $key,
                'rid' => $RID
            );
        }
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
