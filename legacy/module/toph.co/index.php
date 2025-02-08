<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $parse_full = isset($_GET['parse_full_list']);

    $url = $parse_full? url_merge($URL, 'all') : $URL;
    $page = curlexec($url);
    preg_match_all('#<a[^>]*href="?(?P<url>/c/[^">/\#]*)/?"?>\s*(?:<h2[^>]*>)?(?P<title>[^<]*)</#', $page, $matches, PREG_SET_ORDER);
    if ($parse_full) {
        for ($n_page = 2;; $n_page += 1) {
            preg_match_all('#<a[^>]*href="?(?P<url>/c/[^">/\#]*)/?"?>\s*(?:<h2[^>]*>)?(?P<title>[^<]*)</#', $page, $m, PREG_SET_ORDER);
            $matches = array_merge($matches, $m);

            if (!preg_match('#<a[^>]*href="?(?P<href>[^">]*)"?>' . $n_page . '</a>#', $page, $match)) {
                break;
            }
            $page = curlexec($match['href']);
        }
    }

    $seen = array();
    foreach ($matches as $match) {
        $url = url_merge($URL, $match['url']);
        if (isset($seen[$url])) {
            continue;
        }
        $seen[$url] = true;

        $title = $match['title'];
        $title = html_entity_decode($title, ENT_QUOTES);

        $page = curlexec($url);
        if (!preg_match('#(will start|started on) [^<]*<[^>]*(?:data-time|data-timestamp)=(?P<start_time>[0-9]+)[^>]*>(?:[^<]*<[^>]*>[^<]*</[^>]*>)*</[^>]*>[^<]*(will run|ran) for <[^>]*>(?P<duration>[^<]*)</#', $page, $match)) {
            continue;
        }

        $path = explode('/', trim($url, '/'));
        $key = end($path);

        if (strpos($page, "collect your credential from the contest organizer") !== false) {
            $title .= ' [private]';
        }

        $contests[] = array(
            'start_time' => $match['start_time'],
            'duration' => $match['duration'],
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $key,
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
