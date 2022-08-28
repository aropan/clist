<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = 'https://www.icfpconference.org/contest.html';
    $page = curlexec($url);

    $urls = array('http://icfpcontest.org/');

    if (preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<year>[0-9]{4})\b#', $page, $matches, PREG_SET_ORDER)) {
        foreach ($matches as $m) {
            $urls[] = $m['url'];
            if (!isset($_GET['parse_full_list'])) {
                break;
            }
        }
    }
    $year = date('Y');
    $urls[] = "https://icfpcontest$year.github.io/";
    $urls = array_unique($urls);

    $parsed_urls = [];
    foreach($urls as $url) {
        $page = curlexec($url);
        $page = html_entity_decode($page);
        if (in_array($url, $parsed_urls)) {
            continue;
        }
        $parsed_urls[] = $url;

        if (!preg_match('#<title[^>]*>(?P<title>[^<]*\b(?P<year>[0-9]{4})\b[-^<:|]*)#i', $page, $match)) {
            if (!preg_match('#<h1[^>]*>\s*(?:<a[^>]*>)?(?P<title>[^<]*\b(?P<year>[0-9]{4})\b[-^<:|]*)<#i', $page, $match)) {
                continue;
            }
        }
        $year = trim($match['year']);
        $title = trim($match['title']);

        $prepositions = '(?:at|on|from|of|[a-z,\s]+\bis\b)';
        $regex = '#(?:\b(?:contest\s+ran|start[a-z]*|held|(?:took|take)\s+place)\s+' . $prepositions . '?)(\s*<br[^>]*>)?(?:\s*<a[^>]*>)?(?P<start_time>(?:[^<."]*[0-9]+){2,}[^<."]*)#';
        if (!preg_match($regex, $page, $match)) {
            if (!preg_match('#<script[^>]*src="(?P<url>/static/js/main\.[^"]*\.js)"[^>]*>#', $page, $match)) {
                continue;
            }
            $page = curlexec($match['url']);
            if (!preg_match($regex, $page, $match)) {
                continue;
            }
        }
        $time = $match['start_time'];
        $time = preg_replace('#\s*\([^\)]*\)\s*#', ' ', $time);
        $time = preg_replace('#[^0-9]*\s+' . $prepositions . '#', '', $time);
        $time = preg_replace('#\s*\\\[^\s]+\s*#', ' - ', $time);
        $time = preg_replace('#\s*\b(Monday|Mon|Mo|Tuesday|Tue|Tu|Wednesday|Wed|We|Thursday|Thu|Th|Friday|Fri|Fr|Saturday|Sat|Sa|Sunday|Sun|Su)\b\s*#i', ' ', $time);
        $time = preg_replace('#[—–]+#', '-', $time);
        $time = preg_replace('#[^-0-9A-Za-z:]#', ' ', $time);
        $time = preg_replace('#\s+#', ' ', $time);
        $time = preg_replace('#\s*-\s*#', '-', $time);
        $time = trim($time);

        if (strpos($time, '-') !== false) {
            list($start_time, $end_time) = explode('-', $time);
        } else {
            $start_time = $time;
            $end_time = '';
        }
        if (!preg_match('#\b[0-9]{4}\b#', $start_time)) {
            $start_time .= " $year";
        }
        if (!empty($end_time) && !preg_match('#\b[0-9]{4}\b#', $end_time)) {
            $end_time .= " $year";
        }
        if (!strtotime($start_time)) {
            continue;
        }
        if (!empty($end_time) && !strtotime($end_time)) {
            $end_time = '';
        }

        $c = array(
            'start_time' => $start_time,
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $year,
        );
        if (!empty($end_time)) {
            $c['end_time'] = $end_time;
        } else {
            $c['duration'] = '72:00';
        }
        $contests[] = $c;
    }
    if (DEBUG) {
        print_r($contests);
    }
?>
