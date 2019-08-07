<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://acm.timus.ru/schedule.aspx?locale=en";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Asia/Yekaterinburg';
    if (!isset($contests)) $contests = array();

    curl_setopt($CID, CURLOPT_HTTPHEADER,
        array(
            "Host: acm.timus.ru",
            "User-Agent: Mozilla/5.0 (Windows NT 5.1; rv:6.0.2) Gecko/20100101 Firefox/6.0.2",
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language: ru-ru,ru;q=0.8,en-us;q=0.5,en;q=0.3",
            "Accept-Encoding: gzip, deflate",
            "Accept-Charset: utf-8;q=0.7,*;q=0.7",
            "Connection: keep-alive",
            "Referer: http://acm.timus.ru/schedule.aspx",
            "Cookie: ASP.NET_SessionId=ntorsk3ipmyeqc450balwz3p; Locale=English"
        )
    );

    $page = curlexec($URL);

    preg_match_all('#<LI>[^<]*<A HREF="(?<url>[^"]+)">[^<]*</A></LI>#', $page, $matches);
    $urls = array();
    foreach ($matches['url'] as $url) {
        $url = url_merge($URL, $url);
        $urls[] = $url;
    }

    if (isset($_GET['parse_full_list'])) {
        preg_match('#<A[^>]*HREF="(?P<href>[^"]*)"[^>]*>Past contests</A>#i', $page, $match);
        $page = curlexec($match['href']);
        preg_match_all('#<A[^>]*HREF="(?P<href>[^"]*)"[^>]*>Final standings</A>#i', $page, $matches);
        foreach ($matches['href'] as $url) {
            $url = str_replace('monitor.aspx', 'contest.aspx', $url);
            $url = url_merge($match['href'], $url);
            $urls[] = $url;
        }
    }

    foreach ($urls as $url) {
        $url = str_replace('locale=en&', '', $url);
        $page = curlexec($url);

        preg_match('#<H2 CLASS="title">(?<title>.*?)</H2>.*?Contest starts at <B>(?<start_time>.*?)</B>.*?\((?<utc_start_time>UTC[^\)]+)\).*?Contest finishes at <B>(?<end_time>.*?)</B>.*?\((?<utc_end_time>UTC[^\)]+)\)#s', $page, $match);

        $contests[] = array(
            'start_time' => trim($match['start_time']),// . ' ' . trim($match['utc_start_time']),
            'end_time' => trim($match['end_time']),// . ' ' . trim($match['utc_start_time']),
            'title' => trim($match['title']),
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $url
        );
    }

    curl_setopt($CID, CURLOPT_HTTPHEADER, array());
?>
