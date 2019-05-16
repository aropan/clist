<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://russianaicup.ru/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);

    if (!preg_match("#<title>[^<]*-\s*([^<]*)</title>#", $page, $match)) {
        return;
    }
    list($title, $year) = explode(" ", $match[1], 2);

    $amonths = array("января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря");
    $replace_pairs = array();
    foreach ($amonths as $ind => $month)
    {
        $ind = sprintf("%02d", $ind + 1);
        $replace_pairs[" $month"] = ".$ind." . (intval($year) + ($ind < 3? 1 : 0));
    }
    $page = strtr($page, $replace_pairs);

    preg_match_all("#
        <strong>(?P<title>[^<]*)</strong>:
        [^0-9\.]+(?P<start_time>[0-9\.]*[0-9])
        #xi",
        $page,
        $matches,
        PREG_SET_ORDER
    );

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

        $contests[] = array(
            'start_time' => $start_time,
            'duration' => '00:00',
            'title' => $title . '. ' . $round,
            'url' => $URL,
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
