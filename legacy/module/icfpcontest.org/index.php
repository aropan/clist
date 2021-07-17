<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = 'https://www.icfpconference.org/contest.html';
    $page = curlexec($url);

    $urls = array($URL, 'http://icfpcontest.org/');

    if (preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<year>[0-9]{4})\b#', $page, $matches, PREG_SET_ORDER)) {
        foreach ($matches as $m) {
            $urls[] = $m['url'];
            if (!isset($_GET['parse_full_list'])) {
                break;
            }
        }
    }
    $urls = array_unique($urls);

    $parsed_urls = [];
    foreach($urls as $url) {
        $page = curlexec($url);
        if (in_array($url, $parsed_urls)) {
            continue;
        }
        $parsed_urls[] = $url;

        if (!preg_match('#<title[^>]*>(?P<title>[^<]*\b(?P<year>[0-9]{4})\b[^<]*)<#', $page, $match)) {
            continue;
        }
        $year = trim($match['year']);
        $title = trim($match['title']);

        if (!preg_match('#(?:will take place|contest will start(?:\s*at|\s*on))(\s*<br[^>]*>)?\s*(?:<a[^>]*>)?(?P<start_time>[^<.]{4,})#', $page, $match)) {
            if (!preg_match('#<script[^>]*src="(?P<url>/static/js/main\.[^"]*\.js)"[^>]*>#', $page, $match)) {
                continue;
            }
            $js = curlexec($match['url']);
            if (!preg_match('#"on\s*(?P<start_time>[^,"]*,[^@"]*@[^"]*)"#', $js, $match)) {
                continue;
            }
        }
        $time = $match['start_time'];
        $time = preg_replace('#\s*\([^\)]*\)\s*#', ' ', $time);
        $time = preg_replace('#\s*(Monday|Mon|Mo|Tuesday|Tue|Tu|Wednesday|Wed|We|Thursday|Thu|Th|Friday|Fri|Fr|Saturday|Sat|Sa|Sunday|Sun|Su)\s*#i', ' ', $time);

        if (strpos($time, ' - ') !== false) {
            list($start_time, $end_time) = explode(' - ', $time);
            $duration = '';
        } else {
            $start_time = preg_replace('/\s+(?:at|@)/', '', $time);
            $end_time = '';
            $duration = '72:00';
        }
        if (!preg_match('#\b[0-9]{4}\b#', $start_time)) {
            $start_time .= " $year";
        }
        if (!empty($end_time) && !preg_match('#\b[0-9]{4}\b#', $end_time)) {
            $end_time .= " $year";
        }

        if (preg_match_all('#(?P<title>\b[\s*a-z]*)\s*will end(?:\s*at|\s*on)\s*(?:<a[^>]*>)?(?P<end_time>[^<.]*)#', $page, $matches, PREG_SET_ORDER)) {
            foreach ($matches as $m) {
                $title = ucfirst(trim($m['title']));
                $end_time = preg_replace('/\s+at/', '', $m['end_time']);
                $contests[] = array(
                    'start_time' => $start_time,
                    'end_time' => $end_time,
                    'title' => $title,
                    'url' => $url,
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                );
            }
        } else {
            $c = array(
                'start_time' => $start_time,
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
            );
            if (!empty($end_time)) {
                $c['end_time'] = $end_time;
            }
            if (!empty($duration)) {
                $c['duration'] = $duration;
            }
            $contests[] = $c;
        }
    }
    if (DEBUG) {
        print_r($contests);
    }
?>
