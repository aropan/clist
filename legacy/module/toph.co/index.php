<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://toph.co/contests";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();


    $page = curlexec($URL);

    preg_match_all('#<a[^>]*href="?(?P<url>[^">]*)"?[^>]*>\s*<h2[^>]*>(?P<title>[^<]*)</h2>\s*</a>#', $page, $matches, PREG_SET_ORDER);

    $parse_full = isset($_GET['parse_full_list']);
    if ($parse_full) {
        for ($n_page = 2;; $n_page += 1) {
            preg_match_all('#<td[^>]*><a[^>]*href="?(?P<url>[^">]*)"?[^>]*>\s*(?P<title>[^<]*)</a>#', $page, $m, PREG_SET_ORDER);
            $matches = array_merge($matches, $m);

            if (!preg_match('#<a[^>]*href="?(?P<href>[^">]*)"?>' . $n_page . '</a>#', $page, $match)) {
                break;
            }
            $page = curlexec($match['href']);
        }
    }

    foreach ($matches as $match) {
        $url = url_merge($URL, $match['url']);
        $title = $match['title'];

        $page = curlexec($url);
        if (!preg_match('#will start [^<]*<[^>]*data-time=(?P<start_time>[0-9]+)[^>]*>.*?will run for <[^>]*>(?P<duration>[^<]*)</#', $page, $match)) {
            continue;
        }

        $path = explode('/', trim($url, '/'));

        $contests[] = array(
            'start_time' => $match['start_time'],
            'duration' => $match['duration'],
            'title' => html_entity_decode($title, ENT_QUOTES),
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => end($path)
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
