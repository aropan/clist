<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://hsin.hr/coci/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $debug_ = $RID == -1;

    $url = $URL;
    $page = curlexec($url);
    $urls = array($url);
    if (preg_match_all('#<a[^>]*href="(?P<url>archive/[0-9_]*/[^"]*)"[^>]*>#', $page, $matches)) {
        foreach ($matches['url'] as $url) {
            $urls[] = url_merge($URL, $url);
        }
    }

    foreach ($urls as $url) {
        $page = curlexec($url);
        if (!preg_match('#[0-9]{4}.[0-9]{4}#', $page, $match)) {
            continue;
        }
        $season = $match[0];
        $season[4] = '-';

        preg_match_all('#<div class="naslov">(?<title>[^<]+)</div>.*?<a [^>]+>(?<date>\d\d\.\d\d\.\d\d\d\d)\.<br />(?<date_start_time>\d\d:\d\d) GMT/UTC#si', $page, $matches, PREG_SET_ORDER);

        foreach ($matches as $m) {
            $title = $m['title'];
            $contests[] = array(
                'start_time' => $m['date'] . ' ' . $m['date_start_time'],
                'duration' => '03:00',
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $season . ' ' . $title,
            );
        }
    }

    if ($debug_) {
        print_r($contests);
    }
?>
