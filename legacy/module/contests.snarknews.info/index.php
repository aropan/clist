<?php
    require_once dirname(__FILE__) . "/../../config.php";
    if (!isset($URL)) $URL = "http://contests.snarknews.info/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    $URLS = array();

    //if (!preg_match('#href="\#nogo">.*?<li><a href="(?<url>[^"]+)">.*?</a></li>#s', $page, $match)) return;
    //$url = (strpos($match['url'], 'http://') !== 0? $URL : '') . $match['url'];
    //$URLS[] = $url;
    if (preg_match_all('#<a[^>]*href="(?<url>[^"]*sn[sw]s\d*(?P<y>\d\d)[^"]*)"[^>]*>#s', $page, $matches, PREG_SET_ORDER)) {
        $max = -1;
        $url = NULL;
        foreach ($matches as $m) {
            $y = (int)$m['y'];
            if ($y > $max) {
                $max = $y;
                $url = $m['url'];
            }
        }
        $url = (strpos($url, 'http://') !== 0? $URL : '') . $url;
        $url = rtrim($url, '/');
        $URLS[] = $url;
    }
    $year = date('Y');
    $URLS[] = "http://snws$year.snarknews.info";
    $URLS[] = "http://snss$year.snarknews.info";
    sort($URLS);
    $URLS = array_unique($URLS);
    foreach ($URLS as $url)
    {
        $page = curlexec($url);

        if (!preg_match('#a href="(?<url>index.cgi?[^"]*schedule[^"]*)"#s', $page, $match)) continue;
        $url = (strpos($match['url'], 'http://') !== 0? $URL : '') . $match['url'];
        $page = curlexec($url);

        if (!preg_match('#<td class="maintext">[^<]*<center>[^<]*<table border=1>.*?</table>#s', $page, $match)) continue;
        $table = $match[0];

        if (!preg_match('#<font[^>]*>(?<title>.*?)</font>#', $page, $match)) continue;
        $title = ucwords(trim(strip_tags($match['title'])));

        preg_match_all('#href="(?<url>http://(?:algorithm\.)?contest[0-9]*\.yandex\.ru/(?:[a-z]+[0-9]+/)?contest/(?P<id>\d+)/enter)"#', $page, $matches, PREG_SET_ORDER);
        usort($matches, function ($a, $b) { return intval($a['id']) < intval($b['id'])? -1 : 1; });
        $urls = [];
        foreach ($matches as $m) {
            $urls[] = str_replace('contest2.yandex', 'contest.yandex', $m['url']);
        }
        $urls = array_unique($urls);

        preg_match_all('#<tr>[^<]*<td>(?<title>.*?)</td>[^<]*<td>(?<start_time>.*?)</td>[^<]*<td>(?<end_time>.*?)</td>.*?</tr>#s', $table, $matches);

        foreach ($matches[0] as $i => $value)
        {
            $contests[] = array(
                'title' => trim(strip_tags($matches['title'][$i])) . '. ' . $title,
                'start_time' => trim(strip_tags($matches['start_time'][$i])),
                'end_time' => trim(strip_tags($matches['end_time'][$i])),
                'duration_in_secs' => (60 + 20) * 60,
                'url' => $i < count($urls)? $urls[$i] : $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => trim(strip_tags($matches['title'][$i])) . '. ' . $title
            );
        }
    }
    if ($RID == -1) {
        print_r($contests);
    }
?>
