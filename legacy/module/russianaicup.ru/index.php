<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://russianaicup.ru/?locale=en";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($HOST_URL)) $HOST_URL = $URL;
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);

    if (!preg_match("#<title>[^<]*-\s*([^<]*)</title>#", $page, $match)) {
        return;
    }
    list($title, $year) = explode(" ", $match[1], 2);

    preg_match_all("#<strong>(?P<title>[^<]*)</strong>:\s*(?P<start_time>[^.]*)\.<#xi", $page, $matches, PREG_SET_ORDER);

    if (preg_match('#<h[^>]*class="[^"]*alignRight[^"]*"[^>]*>(?<title>[^:]*)#', $page, $match)) {
        $rtitle = $match['title'];
        preg_match('#secondsBefore\s*=\s*(?<before>[0-9]+)#', $page, $match);
        $rtime = time() + intval($match['before']);
        $rtime = intval(round($rtime / 3600) * 3600);
    }

    foreach ($matches as $match)
    {
        $round = $match['title'];
        $start_time = isset($rtitle) && $round == $rtitle? $rtime : $match['start_time'];

        if (preg_match('#[0-9]+\s*-\s*[0-9]+#', $start_time)) {
            $end_time = preg_replace('#[0-9]+\s*-\s*([0-9]+)#', '\1', $start_time);
            $start_time = preg_replace('#([0-9]+)\s*-\s*[0-9]+#', '\1', $start_time);
        } else {
            $end_time = $start_time;
        }

        if (substr_count($start_time, " ") > 5) {
            continue;
        }

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title . '. ' . $round,
            'url' => $HOST_URL,
            'host' => $HOST,
            'key' => $title . '. ' . $round,
            'rid' => $RID,
            'timezone' => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
